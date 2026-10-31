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
/* GUARDRAIL: MEMSZ must be sized to the POOL, not to the baked image. image.h declares
 * `static u8 mem[MEMSZ]`, so every byte above V_HERE (1 136 B) costs exactly one pool byte, and
 * 1 872 puts the whole pool at 7 856 B with 736 B of app space. It sat at 1 280 for weeks, which left
 * 592 B of the pool idle while app space was 144 B; the docs compounded the error by quoting 620 B,
 * a figure that needed MEMSZ 2 196 and therefore an 8 180 B pool (E-054). Overflow past 1 872 is NOT
 * caught by the linker — check the size report, not the link. */
/* GUARDRAIL: pool = MEMSZ + 5798 with the 64/128 rings (data is MEMSZ+8, text 4830, bss 960), so the
 * ceiling is 2058 and not the 2064 the previous arithmetic implied — the ring edit itself moved text by
 * 6 B. 2 048 is the round number that keeps a 10 B margin: app space 912 B, pool 7 846 of 7 856.
 * Recompute this constant whenever .text or .bss changes; overflow is silent (E-054). */
/* GUARDRAIL: MEMSZ and src/image.h are ONE decision, not two. The image embeds V_LATEST as an absolute
 * address (base of the header area), so raising MEMSZ without re-baking points the dictionary outside
 * mem[]: the link succeeds, the boot assert is the only thing between that and "every word is unknown"
 * (E-079). Re-bake with tools/bake.sh <MEMSZ>, which owns the flag set, whenever this number moves.
 * 1 200 -> 1 400 is paid for exactly by the mailbox shrink in uforth.c (216 B -> 16 B of .bss). */
#define MEMSZ    2024          /* GUARDRAIL: with blocks on, the 256 B window lives INSIDE mem[], so every byte here is 1:1 pool:
 * 1 704 left the image 131 B over the 7 856 B limit with the block layer linked; 1 500 lands at ~7 780.
 * App space is (MEMSZ - BLKSZ - headers) - V_HERE, which the countdown now computes from V_LATEST. */
#define SD        16            /* P13: peak 108 B */
#define TIBSZ     128           /* P22: the line buffer, matched to the ring size */
/* P47: the VM switch was two libgcc `memcpy` calls (136 B struct copies) and a `memset`, 127
 * instructions = 7 % of text. uforth.c already carries hand-written word copies behind this flag;
 * measured here at -356 B (text 5 156 -> 4 800), which is the largest byte win available without
 * deleting a requirement. Spent on MEMSZ: app space 226 -> 578 B, R4 intact. */
/* GUARDRAIL: P33_BLOCK/BLKPRIM/BLKSZ/BLK_MB live HERE, in the same header the bake must use, because
 * BLKADR = MEMSZ - BLKSZ is baked into the image as an absolute and computed again in the ULP; a bake with
 * a different BLKSZ puts the buffer where the dictionary expects it to be and the first fetch overwrites
 * definitions (F-107's cousin). 256 B halves the window; at 144 us per fetch the extra fetches are cheap
 * per command, and 512 B does not fit the pool alongside R4.
 * GUARDRAIL: 1 200 / 128 is a MEASURED fitting point, not a preference: with the block primitive bodies
 * actually linked the image is 8 139 B at MEMSZ 1 500 (283 B over the 7 856 B pool), and overflow is
 * silent — the linker succeeds, the ULP stack runs into .bss, and the machine boots printing nothing.
 * 1 200 / 128 lands at 7 839 B and still leaves ~154 B of app space. The honest fix for app space is the
 * primitive subset (~344 B), not a bigger window.
 * GUARDRAIL: the mailbox is 4 words (blk, op, status, checksum) — blk, op and checksum are written before
 * the doorbell and status last, so the ULP never reads a half-copied buffer. */
/* GUARDRAIL: OFF in the P52 bench build only, and off means UNDEFINED — `#define P33_BLOCK 0` still satisfies
 * `#if defined(P33_BLOCK)` at uforth.c:174/473/889, so the first attempt at a lean bench image changed the
 * section sizes by exactly 0 B and cost a build cycle. Blocks cost ~300 B of primitive bodies plus 4 B per
 * header; the P52 workloads use none of them. Lowering MEMSZ instead would move the header area image.h was
 * baked against (F-79: an image baked at a different MEMSZ points outside mem[]). */
#define P33_BLOCK 1
#define BLKPRIM   1
#define BLKSZ     128
#define BLK_MB    4
/* P52: DEVICE BENCH BUILD ONLY — OFF for shipping. P52_LINECYC adds a per-line rdcycle pair and a
 * number-printer, P42_COUNT adds a load/add/store to every dispatch. Measured cost of both: .text
 * 5 250 -> 5 496 and 65 B of pool headroom against the shipping image's 3 B. */
/* #define P52_LINECYC 1 */
/* #define P42_COUNT   1 */
#define P30_HANDCOPY 1
#define P33_NOPAGE 1            /* no frames, no page table */
/* P54 idea 1 (measured in probe/research/P54-ops): 10 same-shape primitive bodies (+ - * AND OR XOR
 * LSHIFT RSHIFT < U<) become one table-driven kernel. Measured there: .text 5 252 -> 4 972, .rodata
 * 308 -> 364, pool -224 B, and the baked dictionary is BYTE-IDENTICAL because no word changes.
 * GUARDRAIL: the rung number is load-bearing. `-DP54_BINOPS` with no value builds rung 1, which measures
 * 0 B — GCC folds a one-entry table back into a direct call, so the kernel does not even exist. A rung
 * below 10 silently measures the old code, which is why the value is written here and not passed ad hoc. */
#define P54_BINOPS 10
/* R4: SPAWN + the task driver. GUARDRAIL: tasks are stepped from run_line(), NOT from inside
 * vm_enter(): vm_switch overwrites the live machine, so a switch taken mid-dispatch would resume the
 * outer interpreter with a task's stacks. The outer VM is saved around the run for the same reason. */
/* GUARDRAIL: OFF. With P43_TASKS the tasks run and interleave correctly (`SPAWN TA SPAWN TB` with
 * PAUSE bodies printed 1 3 2 4), but afterwards the console replays stale command bytes and the REPL
 * is lost — measured with 376 B AND 556 B of C stack, so it is not stack overflow. Root cause not
 * found; do not re-enable until it is. The dictionary is baked: image.h must be regenerated with the
 * same P43_TASKS setting, or SPAWN's header points at a case that is not compiled. */
/* GUARDRAIL: 0 in the P52 bench build only. Tasks cost ~280 B of .bss and ~200 B of text, and the
 * shipping image has 3 B of pool; the scheduler is not in the interpreter's path, so leaving it out does
 * not change dispatch cost or any workload result — it buys the space the instrument needs. */
#define P43_TASKS 1
#define IMAGE

#include "uforth.c"

/* ---------------------------------------------------------------- rings */
/* GUARDRAIL: the rings are pool bytes, and the ULP drains only 32 command bytes per wake, so a 128 B
 * command ring held four wakes' worth of typing that no human can produce (a wake is 6.46 us). 64 B
 * still holds two, and a paste is bounded by it either way. GUARDRAIL: `pl_emit` DROPS when the output
 * ring is full rather than blocking, so shrinking 256 -> 128 makes `repl_out_drop` more likely to be
 * non-zero — keep that counter reachable, or a truncated reply will look like a wrong answer. */
#define CMD_SIZE 64u
#define OUT_SIZE 128u
#define CMD_MASK (CMD_SIZE - 1u)
#define OUT_MASK (OUT_SIZE - 1u)

/* GUARDRAIL: non-static, or the IDF map generator (nm -g) never emits the symbol and the HP side
 * cannot see the rings at all — which looks like "the ULP never ran". */
/* GUARDRAIL: the ring sizes are also compiled into the MAIN CORE (main/repl_main.c), and a mismatch
 * corrupts the console: with the ULP at 64 B and the host still masking with 127, the host wrote past
 * the end of repl_cmd[] into repl_out[] and the REPL replayed stale characters (`3 CUBE .H`,
 * `.HERE?`). Export the sizes so the host can assert them at boot instead of trusting a copy. */
volatile u32 repl_cmd_bytes = CMD_SIZE;
volatile u32 repl_out_bytes = OUT_SIZE;
volatile u8  repl_cmd[CMD_SIZE];
volatile u8  repl_out[OUT_SIZE];
volatile u32 repl_cmd_head;      /* written by the HP */
volatile u32 repl_cmd_tail;      /* written by the ULP */
volatile u32 repl_out_head;      /* written by the ULP */
volatile u32 repl_out_tail;      /* written by the HP */
volatile u32 repl_wake_count;
/* GUARDRAIL: the line/error counters are gone. Both were incremented (per line, per error) and reset at
 * boot, and NOTHING read them — not the HP, not the suite, not the bench, not any tool in the tree. Same
 * class as the depth counters and the switch counters: an increment whose value nobody reads is pure cost
 * (a load, an add, a store per event, plus 4 B of .bss each). `repl_status` deliberately STAYS: it is the
 * only record of why the ULP halted, and the right fix for a diagnostic nobody reads is to make the HP read
 * it, not to delete it. */
volatile u32 repl_out_drop;
volatile u32 repl_status;        /* 1 = booted, 0xE0+rc = error, see below */

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
/* GUARDRAIL: no string emitter here any more. Each message is ONE byte (msg(), uforth.c) that
 * main/repl_main.c expands, so the ULP carries no message text and no string loop. The byte occupies
 * exactly the ring position the text used to, which keeps the operator's transcript and its ordering
 * against the echoed input byte-identical. */


/* One typed line: interpret it, then print the outcome.
 * GUARDRAIL: interpret() consumes tib[0..tl) and stops at tl — it does not wait for a newline, which
 * is why the newline is consumed here and tl reset before the call. */
static void run_line(void)
{
    tl = ti;
    ti = 0;
    interpret();
    if (errf) {
        /* GUARDRAIL: the engine's err() already printed the offending word and '\n'. Printing
         * another message here produced "BOGUS?\n ?\n" — two reports for one error, which teaches
         * a user to distrust both. The engine's report is the one that names the word, so it wins. */
    } else if (sp >= SD) {
        msg(MSG_UNDERFLOW);
        sp = 0;
        rsp = 0;
    } else {
        msg(MSG_OK);
    }
    tl = 0;
    ti = 0;
}

/* Pull at most CMD_BUDGET bytes per wake: enough for typing, small enough that a paste cannot make
 * one wake run for a whole period. The rest stays in the ring for the next wake. */
#define CMD_BUDGET 32u

/* ---------------------------------------------------------- P42 bench ----
 * GUARDRAIL: built only with -DP42_BENCH. The first version was always-on and left the machine
 * answering nothing: input echoed, replies arrived late and batched, and the bench reported
 * `min=567 err=4` for 100 repetitions of a 54-token line. A diagnostic that breaks the machine it
 * measures costs a flash cycle per iteration and invalidates every number it produces, so the
 * default build must not contain it. P42's measurement is therefore still OPEN (RESULT.md). */
#ifdef P42_BENCH_ATTEMPT1_DEAD   /* kept as a record only: see probe-results/P42-RESULT.md */
/* GUARDRAIL: nothing inside this #ifdef has compiled since P42 was abandoned, and its echo(...) calls now
 * name a function that no longer exists (messages are one-byte codes, msg_codes.h). It is prose with line
 * noise, kept for the numbers it records — do not build it and do not copy its echo() calls into live code. */
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
#define BENCH_TAG "p42 base"
#endif
/* GUARDRAIL: no BEGIN/UNTIL here. They are compile-only: typed at the interpreter they silently do
 * nothing useful (measured: `3 BEGIN 1- DUP 0 = UNTIL DROP .` printed `3`, and P42's first run
 * reported 141 684 cycles for what should have been 1 000 iterations). A benchmark that quietly runs
 * once measures nothing, so the workload is a straight line of stack-neutral groups instead:
 * 9 x `1 DUP + DROP` = 117 chars (fits TIBSZ 128), stack-neutral, no control flow. */
#define BENCH_SRC  "1 DUP + DROP 1 DUP + DROP 1 DUP + DROP 1 DUP + DROP 1 DUP + DROP 1 DUP + DROP 1 DUP + DROP 1 DUP + DROP 1 DUP + DROP "
#define BENCH_REPS 100

volatile u32 repl_bench_min;
volatile u32 repl_bench_last;
volatile u32 repl_bench_sp, repl_bench_rsp, repl_bench_err;

/* Print one number with the engine's own '.' — the ULP has no libc formatter. Clears errf first so a
 * previous failure cannot suppress the diagnostic we are asking for. */
static void saynum(u32 v)
{
    errf = 0; sp = 0; rsp = 0;
    ds[0] = v; sp = 1u;
    tib[0] = '.'; tib[1] = ' '; tl = 2u; ti = 0u;
    interpret();
    tl = 0u; ti = 0u; sp = 0;
}

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
    repl_bench_sp = sp; repl_bench_rsp = rsp; repl_bench_err = (u32)errf;
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
    echo("\n" BENCH_TAG " min="); saynum(best);
    echo(" err="); saynum(repl_bench_err);
    echo(" sp=");  saynum(repl_bench_sp);
    echo(" rsp="); saynum(repl_bench_rsp);
    /* GUARDRAIL: fail loud on a dirty stack, but report the numbers first. P42's first run said only
     * "stack/err dirty" and cost a rebuild+reflash to learn nothing; a diagnostic that withholds the
     * values it already has is a second bug. */
    if (repl_bench_err || repl_bench_sp != 0u || repl_bench_rsp != 0u) {
        echo("\nbench: DIRTY, cycles void\n"); return;
    }
    echo("\n");
}

static int is_bench_line(void)
{
    return ti == 5u && tib[0] == 'B' && tib[1] == 'E' && tib[2] == 'N' && tib[3] == 'C' && tib[4] == 'H';
}
#endif /* P42_BENCH */

#ifdef P52_LINECYC
/* ------------------------------------------------- P52 line cycle records ----
 * GUARDRAIL: the instrument sits OUTSIDE the path it measures. rdcycle is read at the LINE BOUNDARY in
 * drain_cmd(), never inside interpret() or vm_enter(): P42 attempt 1 put instrumentation in the dispatch
 * loop and invalidated every cycle it reported. Two reads per line against a ~1e6-cycle workload is noise.
 * GUARDRAIL: publish the record count LAST. The host prints a slot only when the count says it is new, so a
 * count written before its values would print a half-written record — the same write-status-last rule the
 * block mailbox already follows. A "" ::: "memory" barrier keeps the compiler from sinking the stores.
 * GUARDRAIL: no record array. The first version kept 8 (cycles, dispatches) slots so the host could read them
 * later, and that cost 68 B of .bss for a buffer nothing read — the values are printed straight from locals
 * immediately after the bracket closes, which is also the only way to keep them attributable to the line that
 * produced them. Publishing the count LAST stays the rule for anything that does get published. */
static u32 linec_t0, lined_t0;

/* GUARDRAIL: the ULP has no libc formatter, so a number is printed by the ENGINE: push it, then interpret
 * ".". That costs ~1 600 cycles and therefore runs AFTER the bracket closes — never inside it. */
static void saynum(u32 v)
{
    errf = 0; sp = 0; rsp = 0;
    ds[0] = v; sp = 1u;
    tib[0] = '.'; tib[1] = ' '; tl = 2u; ti = 0u;
    interpret();
    tl = 0u; ti = 0u; sp = 0;
}

static void line_bench_begin(void)
{
    __asm__ volatile ("rdcycle %0" : "=r"(linec_t0));
    lined_t0 = p42_dispatches;
}

static void line_bench_end(void)
{
    u32 c, cyc, dsp;
    __asm__ volatile ("rdcycle %0" : "=r"(c));
    cyc = c - linec_t0;
    dsp = p42_dispatches - lined_t0;
    /* marker on its own line: "C <cycles> D <dispatches>" — the driver parses exactly this */
    pl_emit('\n'); pl_emit('C'); pl_emit(' '); saynum(cyc);
    pl_emit('D'); pl_emit(' '); saynum(dsp); pl_emit('\n');
}
#endif /* P52_LINECYC */

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
#ifdef P52_LINECYC
            line_bench_begin();
#endif
            run_line();
#ifdef P52_LINECYC
            line_bench_end();
#endif
        } else if (c == 8 || c == 127) {
            if (ti > 0) { ti--; msg(MSG_ERASE); }
        } else if (c >= 32 && c < 127) {
            if (ti < TIBSZ - 1) { tib[ti++] = c; pl_emit(c); }
            else { msg(MSG_LINE_TOO_LONG); tl = 0; ti = 0; }
        }
        /* other control bytes are ignored and not echoed, by design (06-repl.md §4) */
    }
    repl_cmd_tail = t + n;
}

/* P42 bench, attempt 2 — included after uforth.c so it sees the engine's internals, and only in a
 * bench build. GUARDRAIL: called from main() at boot, never from inside the drain path. */
#ifdef P42_BENCH
#include "p42_bench.inc"
#endif

int main(void)
{
    /* GUARDRAIL: no rdcycle at wake entry. It fed `repl_cyc_start`, which was written on EVERY wake and
     * read by nothing in this tree (the only similar reader is p39_main.c, which reads a different variable
     * in the P39 probe). An rdcycle plus a store per 6.46 ms wake for a value nobody reads is pure cost —
     * the same audit that removed the depth, switch, line and block-error counters. */
    /* GUARDRAIL: the baked image carries absolute addresses (V_LATEST is the header area's base), so an
     * image baked at a different MEMSZ is not merely stale — it points outside mem[]. Check the shape
     * before the first lookup, because the failure mode otherwise is "every word is unknown" and it looks
     * like a broken interpreter rather than a bad image. */
    image_boot_assert();

    if (repl_magic != REPL_MAGIC_RAN) {
        repl_magic = REPL_MAGIC_RAN;
        repl_cmd_head = 0; repl_cmd_tail = 0;
        repl_out_head = 0; repl_out_tail = 0;
        repl_wake_count = 0;
        repl_out_drop = 0; repl_status = 1;
        tl = 0; ti = 0; sp = 0; rsp = 0;
        /* GUARDRAIL: these two globals exist for the MAIN CORE to compare against its own constants,
         * so nothing on the ULP reads them and --gc-sections deletes them — the host then fails to
         * build with "'ulp_repl_cmd_bytes' undeclared". Asserting them here is a real check (the
         * exported value must describe the arrays that exist) and keeps them alive. */
        if (repl_cmd_bytes != (u32)sizeof repl_cmd || repl_out_bytes != (u32)sizeof repl_out)
            pl_halt(0x60);
        msg(MSG_BANNER);     /* GUARDRAIL: the prompt must arrive from the ULP itself, so
                                        * "the HP printed it" can never be mistaken for "Forth ran". */
#ifdef P42_BENCH
#ifdef P42_ONLY
        /* GUARDRAIL: a bench-only main never reads the command ring, so --gc-sections deletes it and the
         * IDF map generator stops exporting ulp_repl_cmd — the main core then fails to build with
         * "'ulp_repl_cmd' undeclared", which reads like a CMake error. Keep one real reference. */
        repl_cmd[0] = repl_cmd[0];
#endif
        p42_run();                  /* once, at boot — never inside the drain (P42 attempt 1) */
#endif
    }

#ifdef P42_ONLY
    /* bench image: report once and retire. drain_cmd()/run_line() are then unreferenced and
     * --gc-sections removes them, which is what keeps this image inside the 7 856 B pool. */
    return 0;
#else
    /* GUARDRAIL: republished on EVERY wake, not once. `repl_magic` lives in RTC RAM, which survives a
     * reset, so after flashing a new image the first-run block is skipped and the host reads the PREVIOUS
     * image's addresses — measured: the block size read 0, every SAVE nacked with a bogus +4, and no byte
     * ever moved. Four stores per wake is nothing against handing the host a wrong pointer.
     * GUARDRAIL: these are OFFSETS into RTC slow memory; the host adds SOC_RTC_DATA_LOW. */
    repl_mem_addr = (u32)&mem[0];
    repl_blk_off  = (u32)BLKADR;
    repl_blk_sz   = (u32)BLKSZ;
    repl_mb_addr  = (u32)&mailbox[0];

    drain_cmd();

#ifdef P43_TASKS
    /* Cooperative step, ONCE per wake and only after the drain has finished and published
     * repl_cmd_tail. GUARDRAIL: this began inside run_line(), i.e. mid-drain, and the machine then
     * re-delivered old command bytes and echoed text from earlier lines — a task switch taken while
     * drain_cmd's cursor is live is the same re-entrancy mistake as P42's bench inside the input path.
     * GUARDRAIL: no `VM outer = vm_live` save. That copy is 136 B of C stack against a 320 B reserve,
     * and it would trade a silent stack overflow for a saved stack. vm_switch overwrites vm_live, so
     * require a clean prompt instead: sp/rsp must be zero, and refusal is loud.
     */
    if (vm_next_ready(-1) >= 0) {
        if (sp != 0u || rsp != 0u) {
            /* GUARDRAIL: report ONCE and retire the pending task. The first version only reported, so
             * the still-ready task was retried on every wake (6.46 ms) and the message repeated
             * hundreds of times — measured as a wall of "tasks need an empty stack" filling the log.
             * Retiring is loud, bounded, and recoverable: spawn again from a clean prompt. */
            int k;
            for (k = 0; k < NTSK; k++) if (tsk[k].state == 1) tsk[k].state = 2;
            msg(MSG_TASK_STACK);
        } else {
            vm_run_tasks();
        }
    }
#endif

    repl_wake_count = repl_wake_count + 1u;
#endif
    return 0;                            /* -> ulp_riscv_halt(): DONE, timer re-arms */
}
