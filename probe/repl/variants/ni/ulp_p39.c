/* ulp_p39.c — P39: the first execution of our engine on the ULP.
 *
 * One wake does everything once: interpret ONE hardcoded line against the prelude that was compiled
 * on the PC and baked into the image, publish the output bytes and a wake counter, retire.
 * Later wakes only bump the counter, so "the ULP never ran" and "the ULP ran and trapped" are
 * distinguishable from the HP side.
 *
 * Scope, deliberately: no blocks (no -DP33_BLOCK), no frames/paging (-DP33_NOPAGE), no tasks, no
 * paging, no REPL. The knobs are set here as #defines, before the engine, so the image is one
 * translation unit and the numbers in RESULT.md are the numbers compiled.
 */
/* GUARDRAIL: the image is 7856 B (8176 minus P21's 320 B C stack) and the *measured* bill for
 * compiling the prelude on-chip was 14 874 B — .rodata 4 350 (the 3 685 B prelude text) plus a
 * SECOND 4 336 B instantiation of the dispatch switch, because interpret() is static and GCC
 * inlined run()/vm_enter() into main() as well as keeping the copy in interpret(). So P39 uses the
 * path the engine's own header documents: the prelude is compiled on the PC into image.h and baked
 * into the ULP binary. main() then interprets the one line against that dictionary. The on-chip
 * prelude compile is priced in RESULT.md as the follow-up it is, not silently dropped. */
#define MEMSZ     1280          /* baked dictionary is 1136 B (host `-d`), 144 B spare */
#define SD        16            /* stack depth, cells (P13: peak 108 B) */
#define TIBSZ     128           /* P22's line buffer */
#define P33_NOPAGE 1            /* no frames, no page table: the probe's "no paging" */
#define IMAGE                   /* mem[] = the host-compiled prelude, in .data, loaded by the .bin */

#if defined(P39_HARNESS_ONLY)
/* Control image (P22's stub-subtraction discipline): the hooks and main() with no engine at all, so
 * "the engine's size" is a measurement and not an estimate. GUARDRAIL: the control must keep the
 * engine's *types* and drop its *code* — including uforth.c in the control leaves all of it in the
 * object and gc-sections only removes it at link time, which would price the harness at zero. */
#include <stdint.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef int32_t i32;
#define rd32(a) 0u                 /* the control touches V_HERE for the same store the real one does */
#else
#include "uforth.c"
#endif

static const char P39_LINE[] = "2 3 + 4 * .\n";

/* ====================================================================
 * Shared memory: the only channel back to the HP core.
 * ====================================================================
 * GUARDRAIL: every one of these must be a non-static global — the IDF map generator runs `nm -g` on
 * the ELF, so a `static` symbol is invisible to the HP side and the run would look like "the ULP
 * never ran" with the answer sitting right there in RTC memory.
 * GUARDRAIL: these are read by the HP *after* the ULP retires, and never written by the HP — writing
 * our own variables from the HP while the ULP is mid-wake is the class of race the board rules ban.
 */
volatile u32 p39_wake_count;     /* .bss: cleared by the first entry, below (see p39_magic) */
volatile u32 p39_cyc_start;      /* rdcycle at wake entry, the first thing main() does */
volatile u32 p39_stage;          /* 1 booted, 2 prelude compiled, 3 line interpreted, 0xE0+rc, 0xF1 err */
volatile u32 p39_here_boot;      /* V_HERE after boot_init() — primitives only */
volatile u32 p39_here_prelude;   /* V_HERE after the prelude — the dictionary the line runs on */
volatile u32 p39_out_word;       /* up to 4 emitted bytes, little-endian, first byte in bits 0..7 */
volatile u32 p39_out_len;        /* bytes emitted (may exceed 4: the word above keeps the first 4) */
volatile u32 p39_sp;             /* data stack pointer after the line */
volatile u32 p39_rsp;            /* return stack pointer after the line */
volatile u32 p39_errf;           /* the engine's error flag after the line */
volatile u32 p39_done;           /* work finished on some earlier wake */

/* GUARDRAIL: `.bss` is NOT in the ULP .bin — ulp_riscv_load_binary writes .text/.rodata/.data only,
 * so an uninitialised static holds whatever the previous image left in RTC RAM (P22 proved mem[] is
 * unloaded .bss). A zero-initialised variable also lands in .bss, so the "has this run before?"
 * question is asked with a NON-zero magic, which stays in .data and therefore is re-loaded. */
static volatile u32 p39_magic = 0x50333900u;
#define P39_MAGIC_RAN 0x50333901u

/* ====================================================================
 * The four platform hooks
 * ==================================================================== */

/* P39: the output IS the evidence, so pl_emit keeps the bytes themselves — a counter or a ring with
 * no reader would let "it printed 20" be a claim rather than a byte. 4 bytes is one decimal answer
 * plus room to see a wrong one; a longer answer still raises p39_out_len past 4, so truncation is
 * visible on the HP instead of silent. */
void pl_emit(int c)
{
    u32 n = p39_out_len;
    if (n < 4u) p39_out_word |= ((u32)(c & 0xff)) << (8u * n);
    p39_out_len = n + 1u;
}

/* Nothing to read from: the one line is a constant, and a REPL is out of scope. -1 is what an empty
 * caller returns, so KEY puzzles nobody. */
int pl_key(void) { return -1; }

/* No GPIO/ADC/MS/WAKE in this line. The store keeps the hook real (P29's lesson: a hook nothing
 * touches is a stubbed hook and its budget line is a lie). */
u32 pl_hw(int op, u32 a, u32 b)
{
    (void)a; (void)b;
    /* GUARDRAIL: op 3 (MS) is a REAL busy-wait in the shipping image (src/ulp_repl.c, rdcycle, 19 000 cycles/ms). This
     * P39 probe keeps the old stub on purpose - it interprets one constant line and no test here uses MS - but do not
     * copy this file's hook back into ulp_repl.c: a stub that returns the wake count looks like a sleep to every caller
     * and is how a demo ran at 267 frames/s (F-124, F-125). */
    if (op == 3) return p39_wake_count;      /* ms: the wake clock is the only clock here */
    return 0;
}

void pl_halt(int code) { p39_stage = 0x100u + (u32)code; }

/* ====================================================================
 * The one line
 * ==================================================================== */
/* GUARDRAIL: one_line() is written out rather than reusing the deleted load_text(): tib must be
 * filled and tl/ti set before interpret(), and a line without its trailing newline must still be
 * interpreted (interpret() stops at tl, it does not wait for EOL). */
#if !defined(P39_HARNESS_ONLY)
static u32 one_line(const char *s)
{
    u8 n = 0;
    while (s[n] && s[n] != '\n' && n < TIBSZ - 1) { tib[n] = (u8)s[n]; n++; }
    tl = n; ti = 0;
    interpret();
    return errf ? 1u : 0u;
}
#endif

/* ====================================================================
 * main() — re-entered by the ULP hardware on every timer wake
 * ==================================================================== */
int main(void)
{
    u32 c;

    /* rdcycle first, before anything can clobber it: P05 measured 81 cycles of wake entry, so this
     * is the wake-start stamp the HP reports. */
    __asm__ volatile ("rdcycle %0" : "=r"(c));
    p39_cyc_start = c;

    if (p39_magic != P39_MAGIC_RAN) {
        u32 rc;
        p39_magic = P39_MAGIC_RAN;
        /* first entry: clear the .bss state we were not able to initialise at load time */
        p39_wake_count = 0; p39_stage = 0; p39_out_word = 0; p39_out_len = 0;
        p39_sp = 0; p39_rsp = 0; p39_errf = 0; p39_done = 0;
        p39_here_boot = 0; p39_here_prelude = 0;

        /* The dictionary arrived in .data, so boot_init() must NOT run here — it would lay the
         * primitive headers over the baked prelude and the line would find `+` but not `.`.
         * GUARDRAIL: this is the -DIMAGE contract (uforth.c guards boot_init with #ifndef IMAGE for
         * the same reason); a run that calls both measures an empty prelude and reports `. ?`. */
        p39_here_boot = rd32(V_HERE);            /* 1136 = the host dump's own figure (0 in the control) */
        p39_stage = 1;

#if defined(P39_HARNESS_ONLY)
        rc = (u32)P39_LINE[0];
#else
        rc = one_line(P39_LINE);
#endif
#if !defined(P39_HARNESS_ONLY)
        p39_sp = sp; p39_rsp = rsp; p39_errf = errf;
        p39_here_prelude = rd32(V_HERE);
#endif
        p39_stage = rc ? 0xF1u : 3u;
        p39_done = 1;
    }

    p39_wake_count = p39_wake_count + 1u;
    return 0;
}
