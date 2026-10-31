/* p45_bench.inc — P45: where do the 1 139 cycles of a dispatch go?
 *
 * Two workloads, same interpreter, different call/dispatch ratio:
 *   A  one colon word with a long body   -> 1 vm_enter call, many dispatches (prologue amortised)
 *   B  a line of primitive `+` calls      -> 1 vm_enter call per dispatch (prologue every time)
 * The per-dispatch cost of the two differs by the prologue+epilogue, which the disassembly says is
 * 24 of ~47 instructions (12 spill + 12 reload + frame).
 *
 * GUARDRAIL: measure cycles per DISPATCH, not per line. The two workloads have very different token
 * counts for the same amount of arithmetic; comparing line totals would just compare their sizes.
 */
#define P45_REPS 24

volatile u32 repl_bench_min, repl_bench_last, repl_bench_sp, repl_bench_rsp, repl_bench_err;

static void p45_hex(u32 v)
{
    int i;
    for (i = 28; i >= 0; i -= 4) {
        u8 d = (u8)((v >> i) & 15u);
        pl_emit(d < 10u ? (char)('0' + d) : (char)('a' + d - 10u));
    }
}

/* "0" (N x "1+ ") "DROP": colon words — long body, one call. */
static u32 p45_fill_colon(u32 groups)
{
    u32 n = 0, g;
    tib[n++] = '0'; tib[n++] = ' ';
    for (g = 0; g < groups; g++) { tib[n++] = '1'; tib[n++] = '+'; tib[n++] = ' '; }
    tib[n++] = 'D'; tib[n++] = 'R'; tib[n++] = 'O'; tib[n++] = 'P';
    return n;
}

/* "1 1 + 1 + ... DROP": every `+` is a primitive call from interpret(). */
static u32 p45_fill_prims(u32 pluses)
{
    u32 n = 0, g;
    tib[n++] = '1'; tib[n++] = ' ';
    for (g = 0; g < pluses; g++) { tib[n++] = '1'; tib[n++] = ' '; tib[n++] = '+'; tib[n++] = ' '; }
    tib[n++] = 'D'; tib[n++] = 'R'; tib[n++] = 'O'; tib[n++] = 'P';
    return n;
}

__attribute__((noinline)) static u32 p45_line(u32 kind, u32 count, u32 *disp, u32 *calls)
{
    u32 t0, t1, d0, c0, n;
    n = (kind == 0u) ? p45_fill_colon(count) : p45_fill_prims(count);
    tl = (u8)n; ti = 0u; sp = 0u; rsp = 0u; errf = 0;
    d0 = p42_dispatches; c0 = p45_calls;
    __asm__ volatile ("rdcycle %0" : "=r"(t0));
    p42_call();
    __asm__ volatile ("rdcycle %0" : "=r"(t1));
    *disp = p42_dispatches - d0;
    *calls = p45_calls - c0;
    if (errf || sp != 0u || rsp != 0u || ti != tl) repl_bench_err = 1u;
    tl = 0u; ti = 0u; sp = 0u;
    return t1 - t0;
}

static void p45_run(void)
{
    u32 rep, best[2] = {0u, 0u}, d[2] = {0u, 0u}, c[2] = {0u, 0u}, ts, cs;

    repl_bench_err = 0u;
    /* one validation pass each, before timing anything */
    best[0] = p45_line(0u, 16u, &ts, &cs); d[0] = ts; c[0] = cs;
    best[1] = p45_line(1u, 16u, &ts, &cs); d[1] = ts; c[1] = cs;
    if (repl_bench_err) { echo("\np45 HARNESS INVALID\n"); return; }
    for (rep = 1u; rep < P45_REPS; rep++) {
        u32 x = p45_line(0u, 16u, &ts, &cs);
        if (x < best[0]) best[0] = x;
        if (ts != d[0] || cs != c[0]) repl_bench_err = 2u;
        x = p45_line(1u, 16u, &ts, &cs);
        if (x < best[1]) best[1] = x;
        if (ts != d[1] || cs != c[1]) repl_bench_err = 3u;
    }
    /* GUARDRAIL: the counters must be identical across reps; if the workload changed size between
     * iterations the min is meaningless. This check is 3 instructions and stays. */
    repl_bench_min = best[0]; repl_bench_last = best[1];
    repl_bench_sp = d[0];     repl_bench_rsp = d[1];
    echo("\np45 err=");    p45_hex(repl_bench_err);
    echo(" Acyc=");        p45_hex(best[0]);
    echo(" Adisp=");       p45_hex(d[0]);
    echo(" Acall=");       p45_hex(c[0]);
    echo(" Bcyc=");        p45_hex(best[1]);
    echo(" Bdisp=");       p45_hex(d[1]);
    echo(" Bcall=");       p45_hex(c[1]);
    echo("\n");
}
