/* slice_probe.c — P04: console rings + a sliced outer interpreter, measured on the host.
 *
 * Build: gcc -std=c99 -Wall -Wextra -O1 -o slice_probe slice_probe.c
 * Run:   timeout 600 ./slice_probe > sweep.log 2>&1
 *
 * It includes the *modified* uforth.c from this directory and supplies the platform itself:
 *   - a NUL-terminated command ring of depth C (arrival paced, overflow = dropped_in++),
 *   - an output ring of depth O that is flushed at every wake exit (refused byte = dropped_out++),
 *   - a simulated wake loop: `W` repl_step() calls, then output flush, then the other task.
 * Every loop is bounded twice (iteration count and wall clock) by construction.
 */
#define _POSIX_C_SOURCE 200809L      /* clock_gettime; must precede every include */
#define HOST 1
#define P04_DRIVER 1
#define MEMSZ 8192                 /* dictionary headroom: this probe measures rings, not dict size */
#define main uforth_unused_main
#include "uforth.c"
#undef main

#include <time.h>

/* ---------------- simulated console rings ---------------- */
static u8 in_ring[512], out_ring[512];
static u16 in_cap, in_h, in_t, in_n;
static u16 out_cap, out_h, out_t, out_n;
static unsigned long dropped_in, dropped_out, bytes_out;

static void rings_reset(int C, int O)
{
    in_cap = (u16)C; out_cap = (u16)O;
    in_h = in_t = in_n = 0; out_h = out_t = out_n = 0;
    dropped_in = dropped_out = bytes_out = 0;
}

static int push_in(int c)
{
    if (in_n >= in_cap) { dropped_in++; return 0; }
    in_ring[in_t] = (u8)c; in_t = (u16)((in_t + 1) % in_cap); in_n++;
    return 1;
}

int pl_cmd_pop(void)
{
    int c;
    if (!in_n) return -1;
    c = in_ring[in_h]; in_h = (u16)((in_h + 1) % in_cap); in_n--;
    return c;
}

/* GUARDRAIL: the out ring must refuse, never wrap: a wrapped ring silently eats the tail of an
 * error message, which is the exact failure the repo forbids. Refusals are counted. */
void pl_emit(int c)
{
    bytes_out++;
    if (out_n >= out_cap) { dropped_out++; return; }
    out_ring[out_t] = (u8)c; out_t = (u16)((out_t + 1) % out_cap); out_n++;
}

u32 pl_hw(int op, u32 a, u32 b)
{
    (void)a; (void)b;
    if (op == 5) return in_n ? 1u : 0u;      /* KEY? = ring non-empty */
    return 0;
}

static void flush_out(void) { out_h = out_t; out_n = 0; }   /* wake exit: transport takes it all */

/* ---------------- run state ---------------- */
static double t0;

static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + 1e-9 * (double)ts.tv_nsec;
}

static void vm_reset(void)
{
    sp = rsp = 0; errf = 0; ln_ready = 0; ti = tl = 0;
    tok_max_cost = 0; prim_ops = 0; mem_ops = 0;
    boot_init();
    if (load("boot_min.fs")) { printf("BLOCKED: boot_min.fs failed to compile\n"); exit(2); }
    ti = tl = 0; ln_ready = 0; errf = 0;    /* load() leaves its file cursor in the line buffer */
}

/* ---------------- workloads ---------------- */
typedef struct {
    const char *name;
    u8 *input; u32 len;
    long long rnum, rden;          /* bytes arriving per wake = rnum / rden */
    u32 wake_ns;
} load_t;

typedef struct {
    unsigned long wakes, lines, errs, tokens, steps, prims, memops, active;
    unsigned long tok_wake_max, prim_wake_max, step_line_max, tok_line_max;
    unsigned long single_tok_max, cpt_x100;     /* cpt_x100 = mem_ops*100/prim_ops */
    unsigned in_peak, out_peak, out_wake_max;
    int timed_out;
} stats_t;

#define MAXWAKES 6000000

static stats_t run_case(u8 k, u16 C, u16 O, const load_t *L, int W, u16 nchars)
{
    stats_t s; long long acc = 0; u32 pos = 0; unsigned long idle = 0, line_steps = 0;
    int i;
    memset(&s, 0, sizeof s);
    vm_reset(); rings_reset(C, O);
    while (s.wakes < MAXWAKES) {
        if ((s.wakes & 0x3ff) == 0 && now_s() - t0 > 600.0) { s.timed_out = 1; break; }
        /* host → cmd ring, at the wire/typing rate for this wake */
        acc += L->rnum;
        while (acc >= L->rden && pos < L->len) { acc -= L->rden; push_in(L->input[pos++]); }
        if (in_n > s.in_peak) s.in_peak = in_n;
        /* the wake: W interpreter steps, then the flush, then the other task */
        {
            u32 p0 = prim_ops, m0 = mem_ops;
            unsigned long tk0 = s.tokens, b0 = bytes_out;
            for (i = 0; i < W; i++) {
                int r;
                step_pulled = 0;
                r = repl_step(k, nchars);
                s.steps++; s.tokens += step_tokens;
                if (step_tokens) { s.active++; line_steps++; }
                if (r == REPL_MORE) {
                    /* GUARDRAIL: the scheduler must stop when a step does no work, not when the
                     * ring is merely empty: an empty ring with a half-typed line would otherwise
                     * burn W steps per wake for 6 s of typing and show up as fake latency. */
                    if (step_pulled == 0 && step_tokens == 0) break;
                    continue;
                }
                if (r == REPL_LINE_DONE) s.lines++; else s.errs++;
                if (line_steps > s.step_line_max) s.step_line_max = line_steps;
                if (line_tokens > s.tok_line_max) s.tok_line_max = line_tokens;
                line_steps = 0;
                if (r == REPL_ERR) break;   /* the line was abandoned: back to the scheduler */
            }
            if (s.tokens - tk0 > s.tok_wake_max) s.tok_wake_max = s.tokens - tk0;
            if (prim_ops - p0 > s.prim_wake_max) s.prim_wake_max = prim_ops - p0;
            if (bytes_out - b0 > s.out_wake_max) s.out_wake_max = bytes_out - b0;
            s.prims += prim_ops - p0; s.memops += mem_ops - m0;
        }
        if (out_n > s.out_peak) s.out_peak = out_n;
        flush_out();
        s.wakes++;
        if (pos >= L->len && in_n == 0 && !ln_ready && tl == 0) break;
        if (in_n == 0 && !ln_ready && pos >= L->len) { if (++idle > 100000) break; }
    }
    s.single_tok_max = tok_max_cost;
    s.cpt_x100 = s.prims ? (unsigned long)(s.memops * 100 / s.prims) : 0;
    return s;
}

/* ---------------- the three workloads ---------------- */
static u8 *slurp(const char *path, u32 *len)
{
    FILE *f = fopen(path, "rb"); long n; u8 *b;
    if (!f) { printf("BLOCKED: cannot open %s\n", path); exit(2); }
    fseek(f, 0, SEEK_END); n = ftell(f); fseek(f, 0, SEEK_SET);
    b = malloc((size_t)n + 1);
    if (!b || fread(b, 1, (size_t)n, f) != (size_t)n) { printf("BLOCKED: read %s\n", path); exit(2); }
    fclose(f); b[n] = 0; *len = (u32)n; return b;
}

static u8 *dup_str(const char *s, u32 *len)
{
    size_t n = strlen(s); u8 *b = malloc(n + 1);
    memcpy(b, s, n + 1); *len = (u32)n; return b;
}

/* ---------------- non-blocking KEY (pass criterion) ---------------- */
static int key_empty_test(void)
{
    static char msg[64];
    int i, n = 0, r = REPL_MORE, ok = 1;
    vm_reset(); rings_reset(64, 128);
    memcpy(tib, "KEY", 3); tl = 3; ti = 0; ln_ready = 1;      /* a line is ready, ring is empty */
    sp = 0;
    for (i = 0; i < 8 && r == REPL_MORE; i++) r = repl_step(1, 32);
    /* the error text must be the named one, and nothing may be pushed or consumed */
    for (i = 0; i < (int)out_n && n < 63; i++) msg[n++] = (char)out_ring[(out_h + i) % out_cap];
    msg[n] = 0;
    printf("KEY empty-ring: returns=%s sp=%u ring_bytes=%u out=\"%s\"\n",
           r == REPL_ERR ? "REPL_ERR" : (r == REPL_LINE_DONE ? "REPL_LINE_DONE" : "REPL_MORE"),
           (unsigned)sp, (unsigned)in_n, msg);
    ok &= (r == REPL_ERR);
    ok &= (sp == 0);
    ok &= (in_n == 0);
    ok &= (strstr(msg, "ERR_NO_INPUT") != NULL);
    printf("KEY empty-ring named error, nothing pushed, nothing consumed: %s\n", ok ? "PASS" : "FAIL");
    return ok;
}

/* ---------------- slice equivalence: repl_step(k=1) must equal interpret() ---------------- */
static int slice_equiv_test(void)
{
    static const char *lines[] = {
        "1 2 +", "5 DUP *", ": T2 3 0 DO I LOOP ;", "T2",
        ": CNT2 0 BEGIN 1+ DUP 5 = UNTIL ;", "CNT2",
        ": BAD2 NOSUCHWORD ;", "99 CONSTANT C2", "C2",
        ": DD 7 0 DO I 2 * DROP LOOP ;", "DD",
        "CREATE XV2 42 ,", "XV2 @"
    };
    enum { NLINES = (int)(sizeof lines / sizeof lines[0]) };
    unsigned want[NLINES]; int want_depth[NLINES];
    int i, j, ok = 1;

    /* reference: the whole-line interpreter the 53-test suite uses */
    for (i = 0; i < NLINES; i++) {
        unsigned h = 0; size_t n = strlen(lines[i]);
        vm_reset(); rings_reset(64, 128);
        memcpy(tib, lines[i], n); tl = (u8)n; ti = 0;
        interpret();
        want_depth[i] = (int)sp;
        for (j = 0; j < (int)sp; j++) h = h * 31u + ds[j];
        want[i] = h;
    }

    /* the same lines through repl_step with the smallest slice the sweep uses */
    for (i = 0; i < NLINES; i++) {
        int r = REPL_MORE, it = 0; unsigned h = 0; size_t n = strlen(lines[i]), p;
        vm_reset(); rings_reset(64, 128);
        for (p = 0; p < n; p++) push_in((int)lines[i][p]);
        push_in('\n');
        while (r == REPL_MORE && it < 2000) { r = repl_step(1, 8); it++; }
        if (r == REPL_MORE) { printf("  slice: line %d did not finish (k=1,nchars=8)\n", i); ok = 0; continue; }
        for (j = 0; j < (int)sp; j++) h = h * 31u + ds[j];
        if ((int)sp != want_depth[i] || h != want[i]) {
            printf("  slice: MISMATCH \"%s\" depth %d vs %d\n", lines[i], (int)sp, want_depth[i]);
            ok = 0;
        }
    }
    printf("repl_step(k=1, nchars=8) matches interpret() on %d lines: %s\n", NLINES, ok ? "PASS" : "FAIL");
    return ok;
}

/* ---------------- dictionary cost per source token ---------------- */
static void dict_cost(void)
{
    u32 h0, h1, h2;
    vm_reset();
    h0 = rd32(V_HERE);
    { const char *s = ": TT 2 * 1 + ;"; size_t n = strlen(s); memcpy(tib, s, n); tl = (u8)n; ti = 0; }
    interpret();
    h1 = rd32(V_HERE);
    { const char *s = ": TTT DUP 0> IF 111 ELSE 222 THEN ;"; size_t n = strlen(s); memcpy(tib, s, n); tl = (u8)n; ti = 0; }
    interpret();
    h2 = rd32(V_HERE);
    printf("dict cost: ': TT 2 * 1 + ;' (7 tokens) = %u B -> %.2f B/token\n",
           (unsigned)(h1 - h0), (double)(h1 - h0) / 7.0);
    printf("dict cost: ': TTT DUP 0> IF 111 ELSE 222 THEN ;' (11 tokens) = %u B -> %.2f B/token\n",
           (unsigned)(h2 - h1), (double)(h2 - h1) / 11.0);
    printf("boot image: HERE=%u of %u after boot_min.fs\n", (unsigned)rd32(V_HERE), (unsigned)MEMSZ);
}

int main(int argc, char **argv)
{
    static const u8 kvals[] = { 1, 4, 16, 64 };
    static const u16 cvals[] = { 64, 128, 256 };
    static const u16 ovals[] = { 128, 256 };
    const int W = 4;                       /* interpreter steps per wake (scheduler quantum) */
    const u16 NCH = 32;                    /* ring characters one step may take */
    u32 l60, lpaste, lmix;
    u8 *typed60, *paste, *mix;
    load_t loads[4];
    int ki, ci, oi, li;
    (void)argc; (void)argv;
    t0 = now_s();

    /* (a) one 60-character line typed at 10 chars/s */
    typed60 = dup_str("1 2 3 4 5 6 7 8 9 10 DROP DROP DROP DROP DROP DROP DROP DROP\n", &l60);
    /* (b) a 100-line boot_min.fs-sized file pasted at once (arrival paced at 115200 8N1) */
    paste = slurp("paste100.fs", &lpaste);
    /* (c) interactive: short lines alternating with long : ... ; definitions */
    mix = dup_str(
        "3 4 + DROP\n"
        ": BIG 100 0 DO I 2 * DROP LOOP ;\n"
        "BIG\n"
        "5 DUP * DROP\n"
        ": LONG 7 0 DO I 3 * DROP LOOP ;\n"
        "LONG\n", &lmix);

    /* bytes per wake = (bytes/s) * wake_s ; 115200 8N1 = 11520 B/s, 10 char/s typing */
    loads[0] = (load_t){ "a-typed60-connected", typed60, l60, 1, 10000, 10000 };
    loads[1] = (load_t){ "b-paste100-connected", paste, lpaste, 1152, 10000, 10000 };
    loads[2] = (load_t){ "b2-paste100-autonomous", paste, lpaste, 1152, 1, 100000000 };
    loads[3] = (load_t){ "c-interactive-connected", mix, lmix, 1, 10000, 10000 };

    printf("P04 sweep — W=%d interpreter steps/wake, nchars=%d ring bytes/step\n", W, (int)NCH);
    printf("workloads: typed60=%u B, paste100=%u B, interactive=%u B\n\n", (unsigned)l60,
           (unsigned)lpaste, (unsigned)lmix);
    printf("k,C,O,workload,wakes,lines,errs,tokens,steps,active_steps,tok/active_step,steps/line,"
           "tok/line,tok/wake max,prim/wake max,single-tok max,drops_in,drops_out,in_peak,out_peak,"
           "out_bytes/wake max,out_bytes,memops/prim,timeout\n");

    for (ki = 0; ki < 4; ki++) for (ci = 0; ci < 3; ci++) for (oi = 0; oi < 2; oi++) {
        for (li = 0; li < 4; li++) {
            stats_t s = run_case(kvals[ki], cvals[ci], ovals[oi], &loads[li], W, NCH);
            printf("%u,%u,%u,%s,%lu,%lu,%lu,%lu,%lu,%lu,%.2f,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%u,%u,%u,%lu,%lu,%s\n",
                   (unsigned)kvals[ki], (unsigned)cvals[ci], (unsigned)ovals[oi], loads[li].name,
                   s.wakes, s.lines, s.errs, s.tokens, s.steps, s.active,
                   s.active ? (double)s.tokens / (double)s.active : 0.0,
                   s.step_line_max, s.tok_line_max, s.tok_wake_max, s.prim_wake_max,
                   s.single_tok_max, dropped_in, dropped_out, s.in_peak, s.out_peak,
                   s.out_wake_max, bytes_out, s.cpt_x100,
                   s.timed_out ? "TIMEOUT" : "-");
            fflush(stdout);
        }
    }

    printf("\n");
    key_empty_test();
    slice_equiv_test();
    dict_cost();
    printf("\nelapsed %.1f s\n", now_s() - t0);
    return 0;
}
