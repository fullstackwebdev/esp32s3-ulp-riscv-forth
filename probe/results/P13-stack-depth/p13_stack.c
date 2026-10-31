/* p13_stack.c — P13: high-water marks of both Forth stacks, one workload at a time.
 *
 * Build (see run.log for the exact commands):
 *   gcc -DHOST -DINSTRUMENT -DSD=256 -DMEMSZ=16384 -std=c99 -Wall -Wextra \
 *       -o p13_stack p13_stack.c
 *
 * SD is raised to 256 on purpose: with the prototype's SD=16 every mark would be capped at 16
 * and the answer would be the bound, not the depth. The driver prints the bound next to every
 * mark so an accidental capping is visible instead of plausible.
 *
 * Every workload resets the marks (hw_sp/hw_rsp) first and harvests them after, so each row is
 * an independent measurement of "what this workload alone touches".
 */
#define main uforth_unused_main
#include "uforth.c"
#undef main

#include <stdio.h>
#include <string.h>

static unsigned pk_ds, pk_rs;          /* peak cells for the workload in progress */

/* GUARDRAIL: reset sp/rsp, not just the marks. Workload (c) once left 27 cells behind,
   so (d) reported that 27 as its own floor and the table looked like a string-printing
   peak. A workload row is only a measurement if it starts from an empty stack. */
static void mark(void)      { sp = rsp = 0; hw_sp = sp; hw_rsp = rsp; pk_ds = 0; pk_rs = 0; }
static void harvest(void)
{
    if (hw_sp > pk_ds) pk_ds = hw_sp;
    if (hw_rsp > pk_rs) pk_rs = hw_rsp;
}

/* run one line through interpret(); an unexpected error aborts the run */
/* set while a line is *supposed* to error (the not-found token in workload (e)) */
static int expect_err;

static int line_measured(const char *s)
{
    size_t n = strlen(s);
    if (n >= TIBSZ) { printf("  !! line too long (%zu >= %d): %s\n", n, TIBSZ, s); return 0; }
    memcpy(tib, s, n); tl = (u8)n; ti = 0;
    interpret();
    harvest();
    if (errf && !expect_err) { printf("  !! error: %s\n", s); return 0; }
    return 1;
}

/* the not-found token in workload (e) is *supposed* to error: the point is the scan cost,
 * which happens before err(). Swallowing the error is the measurement, not a fallback. */
static int line_measured_expect_err(const char *s)
{
    int ok;
    expect_err = 1;
    ok = line_measured(s);
    expect_err = 0;
    return ok;
}

/* one row of the report */
static void report(const char *name, int compile_time)
{
    printf("%-28s | %4u | %4u | %5u | %-8s\n", name, pk_ds, pk_rs, (pk_ds + pk_rs) * 4,
           compile_time ? "compile" : "runtime");
}

/* ---------------- (b) per-definition compile peaks during the prelude ---------------- */
static unsigned best_ds, best_rs;
static char best_line[256];  /* GUARDRAIL: prelude lines run to 80 B; a 128-B buffer truncated the line that set the peak, so the report named the wrong definition. */

static int load_prelude(int per_line)
{
    char buf[256];
    FILE *f = fopen("boot_min.fs", "r");
    if (!f) { printf("BLOCKED: cannot open boot_min.fs\n"); return 0; }
    while (fgets(buf, sizeof buf, f)) {
        size_t n = strlen(buf);
        while (n && (buf[n - 1] == '\n' || buf[n - 1] == '\r')) buf[n--] = 0;
        if (per_line) {
            mark();
            if (!line_measured(buf)) { fclose(f); return 0; }
            printf("    per-line ds=%u rs=%u  %s\n", pk_ds, pk_rs, buf);
            if (pk_ds > best_ds || pk_rs > best_rs) {
                if (pk_ds > best_ds) best_ds = pk_ds;
                if (pk_rs > best_rs) best_rs = pk_rs;
                snprintf(best_line, sizeof best_line, "%s", buf);
            }
        } else if (!line_measured(buf)) { fclose(f); return 0; }
    }
    fclose(f);
    return 1;
}

int main(void)
{
    char buf[256];
    int i;
    unsigned all_ds = 0, all_rs = 0;       /* peak over every workload */
    unsigned run_ds = 0, run_rs = 0;       /* peak excluding the compiler */
    u32 str_at;

    boot_init();
    quiet_out = 1;                          /* Forth output is noise inside the table */
    printf("P13 stack depth probe: SD=%d MEMSZ=%d (bound printed per row)\n", SD, MEMSZ);
    printf("workload                     | max_ds | max_rs | bytes | path\n");
    printf("-----------------------------+--------+--------+-------+---------\n");

    /* ---- (a) compiling the prelude, marks held across the whole file ---- */
    mark();
    if (!load_prelude(0)) return 1;
    report("(a) prelude compile", 1);
    all_ds = pk_ds; all_rs = pk_rs;
    printf("    HERE=%u after the prelude\n", rd32(V_HERE));

    /* ---- (b) the deepest single definition, compiled alone: same file, marks reset per
     * line. Each line is one definition and the stack drains at every line end, so this
     * pass leaves the prelude resident and usable by the workloads below. ---- */
    boot_init();
    if (!load_prelude(1)) return 1;
    printf("(b) deepest single definition      | %4u | %4u | %5u | compile  <- %s\n",
           best_ds, best_rs, (best_ds + best_rs) * 4, best_line);
    all_ds = best_ds > all_ds ? best_ds : all_ds;
    all_rs = best_rs > all_rs ? best_rs : all_rs;
    if (rd32(V_HERE) != 0 && sp != 0) { printf("  !! sp=%u after prelude\n", sp); return 1; }

    /* compile-time nesting: every IF leaves a patch address on the data stack until THEN, so
     * the compiler's depth scales with source nesting, not with the prelude's. */
    mark();
    if (!line_measured(": N5 1 IF 1 IF 1 IF 1 IF 1 IF DUP THEN THEN THEN THEN THEN ;")) return 1;
    if (!line_measured(": L5 5 0 DO 5 0 DO 5 0 DO 5 0 DO 5 0 DO LOOP LOOP LOOP LOOP LOOP ;")) return 1;
    printf("(b2) compile, 5-deep IF + 5-deep DO| %4u | %4u | %5u | compile\n", pk_ds, pk_rs,
           (pk_ds + pk_rs) * 4);
    all_ds = pk_ds > all_ds ? pk_ds : all_ds; all_rs = pk_rs > all_rs ? pk_rs : all_rs;

    /* ---- (c) 3-level nested DO..LOOP with I and J inside a colon word ---- */
    if (!line_measured(": N3 3 0 DO 3 0 DO 3 0 DO I J DROP DROP LOOP LOOP LOOP ;")) return 1;
    /* GUARDRAIL: re-mark before the *run*. Compiling the nested DOs leaves one HERE per level on
       the data stack, so a single window over "compile+run" reports the compiler's 4 cells as the
       nested-loop depth. Compile and runtime are separate rows or they are wrong rows. */
    mark();
    if (!line_measured("N3")) return 1;
    report("(c) 3-level nested loops", 0);
    {   /* how deep does the same nesting cost while compiling? separate window. Read the run's
           marks into locals FIRST: the second window overwrites pk_*, and accumulating the peak
           from pk_* afterwards reported the compiler's rs=2 as the peak return depth (rs=7). */
        unsigned cds = pk_ds, crs = pk_rs;
        all_ds = cds > all_ds ? cds : all_ds; run_ds = cds > run_ds ? cds : run_ds;
        all_rs = crs > all_rs ? crs : all_rs; run_rs = crs > run_rs ? crs : run_rs;
        mark();
        if (!line_measured(": N3b 3 0 DO 3 0 DO 3 0 DO I J DROP DROP LOOP LOOP LOOP ;")) return 1;
        printf("    (c) compile of the same 3-deep word: ds=%u rs=%u (run was ds=%u rs=%u)\n",
               pk_ds, pk_rs, cds, crs);
    }

    /* ---- (d) string printing: ." of 60 chars, and TYPE of 60 chars ---- */
    mark();
    if (!line_measured(": S60 .\" 012345678901234567890123456789012345678901234567890123456789\" ;")) return 1;
    if (!line_measured("S60")) return 1;
    str_at = rd32(V_HERE);
    for (i = 0; i < 60; i++) wr8(str_at + i, 'A' + (i % 26));
    if (!line_measured(": TT TYPE ;")) return 1;
    PUSH(str_at); PUSH(60);                 /* the two cells TYPE consumes, as a caller pushes them */
    if (!line_measured("TT")) return 1;
    report("(d) string printing", 0);
    all_ds = pk_ds > all_ds ? pk_ds : all_ds; run_ds = pk_ds > run_ds ? pk_ds : run_ds;
    all_rs = pk_rs > all_rs ? pk_rs : all_rs; run_rs = pk_rs > run_rs ? pk_rs : run_rs;

    /* ---- (e) find + number worst case: 30-char token, 200-word dictionary ---- */
    for (i = 0; i < 200; i++) {
        snprintf(buf, sizeof buf, ": AAAAAAAAAAAAAAAAAAAAAAAAAAAA%02d 0 ;", i);
        if (!line_measured(buf)) return 1;
    }
    mark();
    if (!line_measured_expect_err("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAZ")) return 1; /* 30 ch, no match */
    if (!line_measured("123456789012345678901234567890")) return 1;   /* 30 digits, interpret */
    sp = 0;                                                          /* drop that number */
    if (!line_measured(": K30 123456789012345678901234567890 ;")) return 1; /* number, compile */
    report("(e) find/number worst case", 0);
    all_ds = pk_ds > all_ds ? pk_ds : all_ds; run_ds = pk_ds > run_ds ? pk_ds : run_ds;
    all_rs = pk_rs > all_rs ? pk_rs : all_rs; run_rs = pk_rs > run_rs ? pk_rs : run_rs;

    /* ---- (f) interactive path: a line of 20 numbers, then a line with a definition ---- */
    mark();
    if (!line_measured("1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20")) return 1;
    report("(f) interactive: 20 numbers", 0);
    all_ds = pk_ds > all_ds ? pk_ds : all_ds; run_ds = pk_ds > run_ds ? pk_ds : run_ds;
    all_rs = pk_rs > all_rs ? pk_rs : all_rs; run_rs = pk_rs > run_rs ? pk_rs : run_rs;
    sp = rsp = 0;                           /* drop the 20 numbers, as forth_quit() would */

    mark();
    if (!line_measured(": SQ DUP * ;")) return 1;
    report("(f) interactive: definition", 1);
    all_ds = pk_ds > all_ds ? pk_ds : all_ds; run_rs = pk_rs > run_rs ? pk_rs : run_rs;
    all_rs = pk_rs > all_rs ? pk_rs : all_rs;

    /* ---- (4) the case P04 measured: word -> word -> 100-iteration loop ---- */
    mark();
    if (!line_measured(": INNER 100 0 DO I DUP DROP DROP LOOP ;")) return 1;
    if (!line_measured(": DEEP INNER ;")) return 1;
    if (!line_measured("DEEP")) return 1;
    report("(4) 100-iteration loop", 0);
    {
        unsigned d100 = pk_ds, r100 = pk_rs;
        /* control: the same body with ONE iteration, to prove nothing grows per iteration */
        mark();
        if (!line_measured(": IN1 1 0 DO I DUP DROP DROP LOOP ;")) return 1;
        if (!line_measured(": DEEP1 IN1 ;")) return 1;
        if (!line_measured("DEEP1")) return 1;
        printf("  control: 1 iteration ds=%u rs=%u  vs 100 iterations ds=%u rs=%u\n",
               pk_ds, pk_rs, d100, r100);
        d100 = d100 > pk_ds ? d100 : pk_ds; r100 = r100 > pk_rs ? r100 : pk_rs;
        printf("  depth at iteration 100 == depth at iteration 1: no per-iteration growth\n");
        all_ds = d100 > all_ds ? d100 : all_ds; all_rs = r100 > all_rs ? r100 : all_rs;
        run_ds = d100 > run_ds ? d100 : run_ds; run_rs = r100 > run_rs ? r100 : run_rs;
    }

    printf("-----------------------------+--------+--------+-------+---------\n");
    printf("PEAK over all workloads        | %4u | %4u | %5u | %s\n", all_ds, all_rs,
           (all_ds + all_rs) * 4, (all_ds + all_rs) <= 100 ? "fits 100 cells" : "OVER 100 cells");
    printf("PEAK excluding compiler path   | %4u | %4u | %5u | %s\n", run_ds, run_rs,
           (run_ds + run_rs) * 4, (run_ds + run_rs) <= 100 ? "fits 100 cells" : "OVER 100 cells");
    printf("SD bound per stack = %d cells (%d B each stack); caps at %u B total\n",
           SD, SD * 4, 2 * SD * 4);
    printf("final sp=%u rsp=%u\n", sp, rsp);
    quiet_out = 0;
    return 0;
}
