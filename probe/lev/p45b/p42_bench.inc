/* p42_bench.inc — P42 attempt 2: time the token fetch, once, from main(), before the REPL exists.
 *
 * Included by ulp_repl.c only when P42_BENCH is defined, and paired with P42_COUNT in uforth.c which
 * counts dispatches inside vm_enter().
 *
 * GUARDRAIL: attempt 1 called interpret() 100x from inside drain_cmd(). The machine echoed input without
 * answering and reported `min=567 err=4` for 100 repetitions. Instrumentation placed inside the path it
 * measures measures nothing. This version runs once, at boot, before the drain loop exists.
 *
 * GUARDRAIL: the workload must be COLON words. Attempt 1 used `1 DUP + DROP` — primitives, which
 * interpret() calls straight through C, so no token is ever fetched and the bench timed dictionary
 * lookup. `1+` is `: 1+ 1 + ;`, so executing it fetches its body token by token through rd16.
 *
 * GUARDRAIL: print with hexnum, never with the engine's `.`. Calling interpret() to format a number pulls
 * a second copy of the interpreter into the image: the first bench build measured 8 064 B against a
 * 7 856 B pool, so it trampled its own C stack and reported garbage. A 40-byte hex printer costs nothing
 * and cannot change the machine's state.
 *
 * Two line lengths: per-call overhead is identical, so it cancels in the difference and the slope is
 * cycles per dispatch.
 */
#define P42_REPS    32
#define P42_SHORT_G 8
#define P42_LONG_G  16

volatile u32 repl_bench_min;      /* min cycles, short line */
volatile u32 repl_bench_last;     /* min cycles, long line  */
volatile u32 repl_bench_sp;       /* dispatches, short      */
volatile u32 repl_bench_rsp;      /* dispatches, long       */
volatile u32 repl_bench_err;      /* 0 = harness valid      */

static void hexnum(u32 v)
{
    int i;
    for (i = 28; i >= 0; i -= 4) {
        u8 d = (u8)((v >> i) & 15u);
        pl_emit(d < 10u ? (char)('0' + d) : (char)('a' + d - 10u));
    }
}

/* "0" (N x "1+ ") "DROP" — built in tib so the length cannot drift from the group count. */
static int p45_plus;
static u32 p42_fill(u32 groups)
{
    u32 n = 0, g;
    /* P45: two workloads with the SAME number of parsed words, differing only in how many dispatches
     * they cause. `1` is a literal: parsed and found, then PUSHed by C with no dispatch at all.
     * `1 +` adds exactly one dispatch. So (plus − lits) / groups is the cost of one dispatch, and
     * lits / groups is the cost of parse + dictionary search for one word.
     * GUARDRAIL: keep both lines under TIBSZ 128 or the fill overruns tib into the ring indices and
     * every number after it is fiction (first attempt: 166-char line, 1 020 231 cycles, err=4). */
    if (!p45_plus) {
        for (g = 0; g < groups; g++) { tib[n++] = '1'; tib[n++] = ' '; }
    } else {
        tib[n++] = '1'; tib[n++] = ' '; tib[n++] = '1'; tib[n++] = ' ';
        for (g = 0; g < groups; g++) { tib[n++] = '+'; tib[n++] = ' '; tib[n++] = '1'; tib[n++] = ' '; }
    }
    return n;
}

/* GUARDRAIL: call interpret() through a volatile pointer. A direct call site here made GCC emit a second
 * copy of the 2 586 B inlined interpreter, taking the image to 8 010 B against a 7 856 B pool — the bench
 * then trampled its own C stack and reported garbage (attempt 1's `min=567`). The indirect call costs ~10
 * cycles per line, against ~100 000 cycles of workload, and it is identical in both images. */
static void (*volatile p42_call)(void) = interpret;

static u32 p42_line(u32 groups, u32 *tok)
{
    u32 t0, t1, d0, n;
    n = p42_fill(groups);
    tl = (u8)n; ti = 0u; sp = 0u; rsp = 0u; errf = 0;
    d0 = p42_dispatches;
    __asm__ volatile ("rdcycle %0" : "=r"(t0));
    p42_call();
    __asm__ volatile ("rdcycle %0" : "=r"(t1));
    *tok = p42_dispatches - d0;
    /* validity: a clean machine that consumed the whole line. If this fires, the number is void. */
    /* GUARDRAIL: no sp==0 check — these workloads leave cells on the stack on purpose; only an
     * error, an underflow-wrapped sp above SD, or an unconsumed line invalidate the number. */
    if (errf || sp >= SD || rsp != 0u || ti != tl) repl_bench_err = 1u;
    tl = 0u; ti = 0u; sp = 0u;
    return t1 - t0;
}

static void p42_run(void)
{
    u32 rep, cs, cl, ts = 0u, tlst = 0u, tok_s = 0u, tok_l = 0u;

    repl_bench_err = 0u;
    p45_plus = 0; cs = p42_line(4u, &ts);           /* one validation pass BEFORE timing 64 of them */
    if (repl_bench_err) { echo("\n" BENCH_TAG " HARNESS INVALID\n"); return; }
    tok_s = ts;
    for (rep = 1u; rep < P42_REPS; rep++) {
        p45_plus = 0; u32 c = p42_line(4u, &ts);
        if (c < cs) cs = c;
        if (ts != tok_s) repl_bench_err = 2u;  /* workload drifted between reps */
    }
    p45_plus = 0; cl = p42_line(8u, &tlst); tok_l = tlst;
    for (rep = 1u; rep < P42_REPS; rep++) {
        p45_plus = 0; u32 c = p42_line(8u, &tlst);
        if (c < cl) cl = c;
        if (tlst != tok_l) repl_bench_err = 3u;
    }
    if (tok_l <= tok_s) repl_bench_err = 4u;   /* slope would divide by zero */
    repl_bench_min = cs; repl_bench_last = cl;
    repl_bench_sp = tok_s; repl_bench_rsp = tok_l;

    echo("\n" BENCH_TAG " e=");  hexnum(repl_bench_err);
    echo(" s=");                 hexnum(cs);
    echo(" d=");                 hexnum(tok_s);
    echo(" l=");                 hexnum(cl);
    echo(" L=");                 hexnum(tok_l);
    echo("\n");
}
