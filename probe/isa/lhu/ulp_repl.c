/* ulp_repl.c — the ULP side of the console: a byte pump between two rings and the interpreter.
 *
 * Wake cycle: pull characters out of repl_cmd[], echo them, and on a newline call interpret() and
 * print the prompt. Then retire. Nothing blocks; nothing waits; every wake does a bounded amount.
 *
 * The rings live in RTC memory, which is the only channel to the HP core. The HP writes cmd_head and
 * reads cmd_tail; the ULP is the other way round on each ring. One writer per index, u32-aligned, so
 * no lock is needed for the indices themselves (P27's lesson: the machine state is what needs care,
 * not the counters).
 *
 * GUARDRAIL: the engine's own variables (tib/tl/ti/errf/V_*) are statics inside uforth.c, so this
 * file must include it — and the dictionary must arrive via IMAGE (.data), never boot_init() on the
 * ULP. Calling both lays the primitive headers over the baked prelude and every word resolves wrong
 * while still printing something plausible (P39 measured exactly that).
 *
 * GUARDRAIL: pl_emit must never allocate or block. It writes into repl_out[] and drops bytes when the
 * ring is full, counting the drops in repl_out_drop. A silent drop here would hide a word's output
 * and make a working program look broken.
 */
#define MEMSZ     1280          /* P39's baked dictionary is 1136 B; 144 B spare for new words */
#define SD        16            /* P13: peak 108 B */
#define TIBSZ     128           /* P22: the line buffer, matched to the ring size */
#define P33_NOPAGE 1            /* no frames, no page table */
#define IMAGE

#include "uforth.c"

/* ---------------------------------------------------------------- rings */
#define CMD_SIZE 128u
#define OUT_SIZE 256u
#define CMD_MASK (CMD_SIZE - 1u)
#define OUT_MASK (OUT_SIZE - 1u)

/* GUARDRAIL: non-static, or the IDF map generator (nm -g) never emits the symbol and the HP side
 * cannot see the rings at all — which looks like "the ULP never ran". */
volatile u8  repl_cmd[CMD_SIZE];
volatile u8  repl_out[OUT_SIZE];
volatile u32 repl_cmd_head;      /* written by the HP */
volatile u32 repl_cmd_tail;      /* written by the ULP */
volatile u32 repl_out_head;      /* written by the ULP */
volatile u32 repl_out_tail;      /* written by the HP */
volatile u32 repl_wake_count;
volatile u32 repl_line_count;
volatile u32 repl_err_count;
volatile u32 repl_out_drop;
volatile u32 repl_status;        /* 1 = booted, 0xE0+rc = error, see below */
volatile u32 repl_cyc_start;

/* GUARDRAIL: .bss is not in the ULP .bin (load_binary writes .text/.rodata/.data only), so an
 * uninitialised static holds whatever the previous image left behind. A zero-initialised variable
 * also lands in .bss, so the "have I run before?" flag is a NON-zero magic in .data. */
static volatile u32 repl_magic = 0x52455000u;    /* 'REP.' */
#define REPL_MAGIC_RAN 0x52455001u

/* ---------------------------------------------------------------- hooks */
void pl_emit(int c)
{
    u32 h = repl_out_head;
    u32 t = repl_out_tail;
    if ((h - t) >= OUT_SIZE) {          /* full: drop and count, never overwrite unread bytes */
        repl_out_drop = repl_out_drop + 1u;
        return;
    }
    repl_out[h & OUT_MASK] = (u8)(c & 0xff);
    repl_out_head = h + 1u;
}

/* The REPL reads raw bytes from cmd[] itself, so KEY has nothing to do. -1 is what an empty caller
 * returns, so a program using KEY sees "no input" rather than a stall. */
int pl_key(void) { return -1; }

u32 pl_hw(int op, u32 a, u32 b)
{
    (void)a; (void)b;
    if (op == 3) return repl_wake_count;     /* ms, via the wake clock */
    return 0;
}

void pl_halt(int code) { repl_status = 0x100u + (u32)code; }

/* ---------------------------------------------------------------- REPL */
static void echo(const char *s) { while (*s) pl_emit(*s++); }

/* One typed line: interpret it, then print the outcome.
 * GUARDRAIL: interpret() consumes tib[0..tl) and stops at tl — it does not wait for a newline, which
 * is why the newline is consumed here and tl reset before the call. */
static void run_line(void)
{
    tl = ti;
    ti = 0;
    interpret();
    if (errf) {
        repl_err_count = repl_err_count + 1u;
        /* GUARDRAIL: the engine's err() already printed the offending word and '\n'. Printing
         * another message here produced "BOGUS?\n ?\n" — two reports for one error, which teaches
         * a user to distrust both. The engine's report is the one that names the word, so it wins. */
    } else if (sp >= SD) {
        echo("stack?\n");
        sp = 0;
        rsp = 0;
    } else {
        echo(" ok\n");
    }
    repl_line_count = repl_line_count + 1u;
    tl = 0;
    ti = 0;
}

/* Pull at most CMD_BUDGET bytes per wake: enough for typing, small enough that a paste cannot make
 * one wake run for a whole period. The rest stays in the ring for the next wake. */
#define CMD_BUDGET 32u

/* ---------------------------------------------------------- P42 bench ----
 * One fixed line, run BENCH_REPS times, minimum cycle count reported. The workload is deliberately
 * dumb: a counted BEGIN..UNTIL over prelude words, so nothing but the token fetch differs between
 * the two images being compared (same prelude, same primitives, same text, same count).
 *
 * GUARDRAIL: never compare two builds by counting instructions. P14 measured NEXT at 480 cycles for
 * ~20 instructions — ~24 cycles per instruction — so RTC RAM latency, not opcode count, decides.
 * Only rdcycle on the same workload across two images can answer "did the fetch get faster".
 *
 * GUARDRAIL: keep the bench OUTSIDE the dispatch loop. A token counter inside interpret() would
 * perturb the very cycles being measured; the comparison stays valid only because the workload, not
 * the instrumentation, is what differs. */
#ifndef BENCH_TAG
#define BENCH_TAG "p42 lhu "
#endif
#define BENCH_SRC  "1000 BEGIN 1- DUP 0 = UNTIL DROP"
#define BENCH_REPS 3

volatile u32 repl_bench_min;
volatile u32 repl_bench_last;

static u32 bench_once(void)
{
    u32 t0, t1, i;
    for (i = 0; i < (u32)(sizeof BENCH_SRC - 1); i++) tib[i] = (u8)BENCH_SRC[i];
    tl = (u8)(sizeof BENCH_SRC - 1);
    ti = 0;
    sp = 0; rsp = 0;                  /* a bench starts from a known machine, not from the caller's */
    __asm__ volatile ("rdcycle %0" : "=r"(t0));
    interpret();
    __asm__ volatile ("rdcycle %0" : "=r"(t1));
    tl = 0; ti = 0;
    return t1 - t0;
}

static void bench_run(void)
{
    u32 rep, best = 0u;
    for (rep = 0; rep < BENCH_REPS; rep++) {
        u32 c = bench_once();
        repl_bench_last = c;
        if (rep == 0u || c < best) best = c;
    }
    repl_bench_min = best;
    /* GUARDRAIL: fail loud on a dirty stack. A bench that silently leaked a cell per iteration would
     * report a beautiful number for a workload that stopped being the same workload. */
    if (errf || sp != 0 || rsp != 0) { echo("\nbench: stack/err dirty, result void\n"); return; }
    echo("\n" BENCH_TAG " min=");
    sp = 0; ds[0] = best; sp = 1u;    /* print with the engine's own '.' rather than a C formatter */
    tib[0] = '.'; tib[1] = ' '; tl = 2u; ti = 0u;
    interpret();
    echo("\n");
    tl = 0; ti = 0; sp = 0;
}

static int is_bench_line(void)
{
    return ti == 5u && tib[0] == 'B' && tib[1] == 'E' && tib[2] == 'N' && tib[3] == 'C' && tib[4] == 'H';
}

static void drain_cmd(void)
{
    u32 t = repl_cmd_tail;
    u32 h = repl_cmd_head;
    u32 n = h - t;
    u32 i;

    if (n > CMD_BUDGET) n = CMD_BUDGET;

    for (i = 0; i < n; i++) {
        u8 c = repl_cmd[(t + i) & CMD_MASK];
        if (c == '\r' || c == '\n') {
            pl_emit('\n');
            if (is_bench_line()) bench_run(); else run_line();
        } else if (c == 8 || c == 127) {
            if (ti > 0) { ti--; echo("\b \b"); }
        } else if (c >= 32 && c < 127) {
            if (ti < TIBSZ - 1) { tib[ti++] = c; pl_emit(c); }
            else { echo("\nline too long\n"); tl = 0; ti = 0; }
        }
        /* other control bytes are ignored and not echoed, by design (06-repl.md §4) */
    }
    repl_cmd_tail = t + n;
}

int main(void)
{
    u32 c;
    __asm__ volatile ("rdcycle %0" : "=r"(c));
    repl_cyc_start = c;

    if (repl_magic != REPL_MAGIC_RAN) {
        repl_magic = REPL_MAGIC_RAN;
        repl_cmd_head = 0; repl_cmd_tail = 0;
        repl_out_head = 0; repl_out_tail = 0;
        repl_wake_count = 0; repl_line_count = 0; repl_err_count = 0;
        repl_out_drop = 0; repl_status = 1;
        tl = 0; ti = 0; sp = 0; rsp = 0;
        echo("\nulp forth\n ok\n");     /* GUARDRAIL: the prompt must arrive from the ULP itself, so
                                        * "the HP printed it" can never be mistaken for "Forth ran". */
    }

    drain_cmd();

    repl_wake_count = repl_wake_count + 1u;
    return 0;                            /* -> ulp_riscv_halt(): DONE, timer re-arms */
}
