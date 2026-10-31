/* p46_bench.inc — P46: split the cost of a typed word into (parse + find) and (dispatch).
 *
 * Four measurements, two workloads at two lengths, so the fixed per-line overhead cancels:
 *
 *   L(g) = g x "1 "                  g parsed literals, ZERO dispatches
 *   P(g) = "1 1 " g x ("+ 1 ")        2 + 2g parsed words, g dispatches, stack-neutral (ends with 2)
 *
 *   slope_L = (L8-L4)/4              cycles per parsed literal word  (word() + find() + PUSH)
 *   slope_P = (P8-P4)/4              cycles per group = 2 parsed words + 1 dispatch
 *   dispatch = slope_P - 2*slope_L   cycles per dispatch, excluding parse
 *
 * Derived from P42's *validated* harness (one validation pass before timing, hex output, no interpret()
 * call to print). GUARDRAIL: three defects in P45 came from departing from that harness — a tib overrun,
 * a stack-underflowing workload, and a counter that was not compiled in. The learnings are baked in here:
 * every line is <= 36 chars, every workload is stack-safe, and validity is checked on the first pass.
 */
#define P46_REPS 24

volatile u32 repl_bench_min, repl_bench_last, repl_bench_sp, repl_bench_rsp, repl_bench_err;
/* four results, exported so nothing has to be printed beyond one line */
volatile u32 p46_l4, p46_l8, p46_p4, p46_p8, p46_d4, p46_d8;

static void p46_hex(u32 v)
{
    int i;
    for (i = 28; i >= 0; i -= 4) {
        u8 d = (u8)((v >> i) & 15u);
        pl_emit(d < 10u ? (char)('0' + d) : (char)('a' + d - 10u));
    }
}

/* mode 0: g literals.  mode 1: "1 1 " then g x "+ 1 " */
static u32 p46_fill(u32 mode, u32 g)
{
    u32 n = 0, i;
    if (mode == 0u) {
        for (i = 0; i < g; i++) { tib[n++] = '1'; tib[n++] = ' '; }
    } else {
        tib[n++] = '1'; tib[n++] = ' '; tib[n++] = '1'; tib[n++] = ' ';
        for (i = 0; i < g; i++) { tib[n++] = '+'; tib[n++] = ' '; tib[n++] = '1'; tib[n++] = ' '; }
    }
    return n;
}

static u32 p46_line(u32 mode, u32 g, u32 *disp)
{
    u32 t0, t1, d0, n;
    n = p46_fill(mode, g);
    tl = (u8)n; ti = 0u; sp = 0u; rsp = 0u; errf = 0;
    d0 = p42_dispatches;
    __asm__ volatile ("rdcycle %0" : "=r"(t0));
    interpret();
    __asm__ volatile ("rdcycle %0" : "=r"(t1));
    *disp = p42_dispatches - d0;
    /* GUARDRAIL: no `sp == 0` test. These workloads deliberately leave cells on the stack (mode 0 leaves
     * g of them). An error, an overflowed stack, or an unconsumed line is what invalidates a number. */
    if (errf || sp >= SD || rsp != 0u || ti != tl) repl_bench_err = 1u;
    tl = 0u; ti = 0u; sp = 0u;
    return t1 - t0;
}

static void p46_run(void)
{
    u32 rep, l4, l8, p4, p8, d4, d8, t;

    repl_bench_err = 0u;
    /* one validation pass of each shape before anything is timed */
    l4 = p46_line(0u, 4u, &t); d4 = t;
    l8 = p46_line(0u, 8u, &t); d8 = t;
    p4 = p46_line(1u, 4u, &t); d4 = t;
    p8 = p46_line(1u, 8u, &t); d8 = t;
    if (repl_bench_err) { echo("\np46 HARNESS INVALID\n"); return; }

    for (rep = 1u; rep < P46_REPS; rep++) {
        u32 x;
        x = p46_line(0u, 4u, &t); if (x < l4) l4 = x; if (t != 0u) repl_bench_err = 2u;
        x = p46_line(0u, 8u, &t); if (x < l8) l8 = x; if (t != 0u) repl_bench_err = 3u;
        x = p46_line(1u, 4u, &t); if (x < p4) p4 = x; if (t != 4u) repl_bench_err = 4u;
        x = p46_line(1u, 8u, &t); if (x < p8) p8 = x; if (t != 8u) repl_bench_err = 5u;
    }
    p46_l4 = l4; p46_l8 = l8; p46_p4 = p4; p46_p8 = p8; p46_d4 = 4u; p46_d8 = 8u;
    repl_bench_min = l4; repl_bench_last = p8;

    echo("\np46 err="); p46_hex(repl_bench_err);
    echo(" l4="); p46_hex(l4);
    echo(" l8="); p46_hex(l8);
    echo(" p4="); p46_hex(p4);
    echo(" p8="); p46_hex(p8);
    echo("\n");
}
