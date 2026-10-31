/* p10_test.c - P10 (host): line discipline, escape framing, flow control.
 *
 * One translation unit: the interpreter is included exactly as the baseline suite includes it,
 * and its byte source/sink are routed into the bridge model (bridge.h / bridge.c) through the
 * pl_hooks() seam. The bridge itself never includes or calls anything from uforth.c.
 *
 * Build and run: ./build.sh   (or: gcc -DHOST -std=c99 -Wall -Wextra -o p10_test p10_test.c bridge.c)
 */
#define main uforth_unused_main
#include "uforth.c"
#undef main
#include "bridge.h"

#include <stdio.h>
#include <string.h>

/* ---------------- harness ---------------- */
static int fails, passes;
static const char *group = "";
static void group_set(const char *g) { group = g; printf("\n== %s\n", g); }
static void check(int cond, const char *name, const char *detail)
{
    if (cond) { passes++; printf("  PASS  %s\n", name); }
    else { fails++; printf("  FAIL  %s   [%s] %s\n", name, group, detail ? detail : ""); }
}
static void eq_str(const char *name, const char *got, const char *want)
{
    char buf[512];
    int cond = !strcmp(got, want);
    snprintf(buf, sizeof buf, "got \"%s\" want \"%s\"", got, want);
    check(cond, name, buf);
}
static void eq_u32(const char *name, u32 got, u32 want)
{
    char buf[128];
    snprintf(buf, sizeof buf, "got %u want %u", got, want);
    check(got == want, name, buf);
}

/* ---------------- the bridge under test ---------------- */
static bridge B;
static unsigned char outbuf[8192];
static unsigned outlen;

static int  h_key(void)    { return br_cmd_get(&B); }
static void h_emit(int c)  { br_out_put(&B, c); }

static u32 tos(void) { return ds[(sp - 1) & (SD - 1)]; }

static void drain(void)
{
    int c;
    while ((c = br_out_get(&B)) >= 0)
        if (outlen < sizeof outbuf - 1) outbuf[outlen++] = (unsigned char)c;
    outbuf[outlen] = 0;
}

/* pump the ULP until the ring is empty and no line is in progress (bounded twice) */
static void pump(int maxsteps)
{
    int i;
    for (i = 0; i < maxsteps; i++) {
        if (br_cmd_n(&B) == 0 && tl == 0 && !ln_ready && !line_bad) break;
        repl_step(4, 32);
        drain();
    }
    drain();
}

/* fresh console for each case: dictionary kept, console state and counters cleared */
static void fresh(void)
{
    sp = rsp = 0; errf = 0; ti = tl = 0; ln_ready = 0; line_bad = 0; ctrl_ignored = 0;
    wr32(V_STATE, 0);
    br_init(&B);
    outlen = 0; outbuf[0] = 0;
}

/* offer bytes to the bridge, pumping the ULP whenever it reports XOFF; returns 1 if all went in
 * (the loop is bounded twice: at most `guard` re-offers, each one padded to at most 4294967295) */
static int feed(const unsigned char *buf, unsigned n, int *saw_xoff)
{
    unsigned off = 0;
    int guard = 0;
    while (off < n && guard++ < 4096) {
        unsigned u = br_feed(&B, buf + off, n - off);
        if (saw_xoff && B.xoff) *saw_xoff = 1;
        off += u;
        if (off < n) pump(256);
    }
    return (int)(off == n);
}
static int feeds(const char *s, int *saw_xoff) { return feed((const unsigned char *)s, (unsigned)strlen(s), saw_xoff); }

static void ring_str(char *dst, unsigned cap)
{
    unsigned i, n = B.cmd_n < cap - 1 ? B.cmd_n : cap - 1;
    for (i = 0; i < n; i++) dst[i] = (char)B.cmd[(B.cmd_r + i) % CMD_RING];
    dst[n] = 0;
}
static int count_sub(const char *hay, const char *needle)
{
    int n = 0; const char *p = hay;
    while ((p = strstr(p, needle))) { n++; p++; }
    return n;
}

int main(void)
{
    char buf[512], line[160];
    u32 here0, latest0;

    boot_init();
    if (load("boot_min.fs")) { printf("FATAL: boot_min.fs failed to compile\n"); return 2; }
    pl_hooks(h_key, h_emit);          /* host echo off: the ULP is the only echoer */

    /* ================= escape table (6 cases) ================= */
    group_set("escape table - 06-repl.md section 3");
    {
        fresh();
        check(feed((const unsigned char *)"\x1d\x1d", 2, 0), "ESC ESC accepted", "");
        ring_str(buf, sizeof buf);
        check(B.cmd_n == 1 && (unsigned char)buf[0] == 0x1D,
              "1/6 ESC ESC -> exactly one literal 0x1D into the ULP input", buf);
    }
    {
        fresh();
        check(feeds("\x1d" "f", 0) && B.mode == BR_FRAMED && B.cmd_n == 0 && outlen == 0,
              "2/6 ESC f -> framed mode, nothing reaches the ULP buffer", "");
        check(feeds("\x1d" "p", 0) && B.mode == BR_PASSTHROUGH && B.cmd_n == 0,
              "3/6 ESC p -> passthrough mode, nothing reaches the ULP buffer", "");
    }
    {
        char st[160];
        fresh();
        tl = 3; memcpy(tib, "abc", 3); ti = 1;   /* a part-typed line must not be disturbed */
        check(feeds("\x1d" "s", 0), "ESC s accepted", "");
        drain();                                  /* the state line lands in the out ring */
        br_state_line(&B, st, sizeof st);
        check(outlen > 0 && outlen == strlen(st),
              "4/6 ESC s -> exactly one ASCII state line out", buf);
        check(count_sub((const char *)outbuf, "\n") == 1 &&
              count_sub((const char *)outbuf, "mode=passthrough") == 1,
              "4/6 ESC s -> one line, mode reported, no console bytes added",
              (const char *)outbuf);
        check(B.cmd_n == 0 && tl == 3 && ti == 1 && !memcmp(tib, "abc", 3),
              "4/6 ESC s -> ULP buffer and cursor untouched", "");
    }
    {
        fresh();
        check(feeds("\x1d" "q", 0) && B.quit == 1 && B.cmd_n == 0 && B.mode == BR_PASSTHROUGH,
              "5/6 ESC q -> quit flag set, drops to autonomous, nothing to the ULP buffer", "");
    }
    {
        fresh();
        check(feeds("\x1d" "x", 0), "ESC x accepted", "");
        ring_str(buf, sizeof buf);
        check(B.cmd_n == 2 && (unsigned char)buf[0] == 0x1D && buf[1] == 'x',
              "6/6 ESC x (unknown) -> BOTH bytes reach the buffer verbatim", buf);
    }
    {
        /* the lookahead bound: a 0x1D with no second byte is flushed at the next poll */
        fresh();
        feeds("\x1d", 0);
        br_idle(&B);
        ring_str(buf, sizeof buf);
        check(B.cmd_n == 1 && (unsigned char)buf[0] == 0x1D && !B.esc,
              "trailing ESC at end of burst -> flushed as a literal after one poll", buf);
    }

    /* ================= line discipline (7 cases) ================= */
    group_set("line discipline - 06-repl.md section 4");
    {
        fresh();
        feeds("1 2 +", 0); pump(16);
        check(tl == 5 && sp == 0 && !memcmp(tib, "1 2 +", 5),
              "1/7 printables are buffered, echoed by the ULP, not yet interpreted", (const char *)outbuf);
        eq_str("1/7 ULP echoed the characters", (const char *)outbuf, "1 2 +");
    }
    {
        fresh();
        feeds("12\x08", 0); pump(16);
        eq_str("2/7 BS erases one character and echoes \\b \\b", (const char *)outbuf, "12\b \b");
        eq_u32("2/7 BS leaves one character buffered", tl, 1);
    }
    {
        fresh();
        feeds("12\x7f", 0); pump(16);
        eq_str("3/7 DEL erases one character and echoes \\b \\b", (const char *)outbuf, "12\b \b");
        eq_u32("3/7 DEL leaves one character buffered", tl, 1);
    }
    {
        fresh();
        feeds("1 2 +\r", 0); pump(64);
        eq_u32("4/7 CR ends the line and it is interpreted (+ -> 3)", tos(), 3);
        eq_str("4/7 CR echoes \\n then ok", (const char *)outbuf, "1 2 +\n ok\n");
    }
    {
        fresh();
        feeds("7 1 -\n", 0); pump(64);
        eq_u32("5/7 LF ends the line and it is interpreted (7 1 - -> 6)", tos(), 6);
        eq_str("5/7 LF echoes \\n then ok", (const char *)outbuf, "7 1 -\n ok\n");
    }
    {
        fresh();
        feeds("1 2 \x03\x04+ \r", 0); pump(64);
        eq_u32("6/7 control bytes are ignored and counted (2 of them)", ctrl_ignored, 2);
        eq_u32("6/7 ... the line around them still interpreters to 3", tos(), 3);
        check(!memchr(outbuf, 0x03, outlen) && !memchr(outbuf, 0x04, outlen),
              "6/7 ... and are never echoed", "");
    }
    {
        int i;
        fresh();
        here0 = rd32(V_HERE); latest0 = rd32(V_LATEST);
        for (i = 0; i < 64; i++) feeds("1 ", 0);           /* 128 bytes */
        feeds("2", 0);                                     /* 129 bytes */
        feeds("\r", 0);
        pump(256);
        check(count_sub((const char *)outbuf, "ERR_LINE_TOO_LONG") == 1,
              "7/7 129-byte line -> ERR_LINE_TOO_LONG", (const char *)outbuf);
        eq_u32("7/7 ... line dropped, HERE unchanged", rd32(V_HERE), here0);
        eq_u32("7/7 ... LATEST unchanged (dictionary byte-identical)", rd32(V_LATEST), latest0);
        eq_u32("7/7 ... nothing executed", sp, 0);
        fresh();
        feeds("1 2 +\r", 0); pump(64);
        eq_u32("7/7 ... and the next line still runs (tail discarded, not interpreted)", tos(), 3);
    }
    {
        /* extra case: a line split across two ring refills */
        fresh();
        feeds("5 DU", 0); pump(8);
        check(tl == 4 && sp == 0, "extra: first half of a line resumes mid-line", "");
        feeds("P *\r", 0); pump(64);
        eq_u32("extra: line split across two refills -> 25", tos(), 25);
        eq_str("extra: still echoed exactly once", (const char *)outbuf, "5 DUP *\n ok\n");
    }

    /* ================= XOFF ================= */
    group_set("flow control - 06-repl.md section 5");
    {
        /* 18 lines of "1 2 + DROP\n" = 198 bytes, all valid, stack neutral */
        static unsigned char big[256];
        unsigned n = 0; int l, saw = 0;
        for (l = 0; l < 18; l++) { memcpy(big + n, "1 2 + DROP\n", 11); n += 11; }
        fresh();
        {
            unsigned u = br_feed(&B, big, n);
            eq_u32("bridge stops accepting at the 96-byte water mark (75 % of 128)",
                   u, XOFF_WM);
            check(B.xoff == 1, "bridge reports XOFF", "");
            br_state_line(&B, line, sizeof line);
            check(strstr(line, "XOFF") != NULL, "the state line says XOFF", line);
            /* FINDING F2, asserted as today's behaviour on purpose: the water-mark test runs before
             * escape recognition, so an operator cannot ask for the state line while input is
             * stopped. Fixed by resolving a pending 0x1D before the occupancy test (see RESULT.md). */
            {
                unsigned v = br_feed(&B, (const unsigned char *)"\x1d" "s", 2);
                drain();
                check(v == 0 && outlen == 0,
                      "F2: at the water mark even ESC s is refused -> the state line is unreachable", "");
            }
            saw = 1;
        }
        /* fresh console, then the real drain-and-retry loop: offer, drain, re-offer the rest */
        fresh();
        {
            unsigned off = 0; int guard = 0;
            while (off < n && guard++ < 256) {
                unsigned u = br_feed(&B, big + off, n - off);
                if (B.xoff) saw = 1;
                off += u;
                if (off < n) pump(256);
            }
            pump(256);                            /* final drain: no line left half-read */
            eq_u32("XOFF round trip: every byte of 198 offered and accepted", off, n);
            eq_u32("XOFF round trip: accepted count == fed count", B.accepted, n);
            eq_u32("XOFF round trip: bytes lost", B.dropped, 0);
            eq_u32("XOFF round trip: ring drained", br_cmd_n(&B), 0);
            check(B.cks_in == B.cks_out, "XOFF round trip: bytes arrived in order, none duplicated", "");
            check(saw, "XOFF actually engaged during the round trip", "");
            eq_u32("XOFF round trip: Forth stayed clean (stack neutral, 18 lines ran)", sp, 0);
            check(count_sub((const char *)outbuf, "ERR") == 0 && count_sub((const char *)outbuf, "?") == 0,
                  "XOFF round trip: no line was corrupted", (const char *)outbuf);
        }
    }

    /* ================= double echo ================= */
    group_set("double echo");
    {
        fresh();
        feeds("5 DUP *\r", 0); pump(64);
        eq_str("host echo off -> out is exactly the ULP's echo, byte for byte",
               (const char *)outbuf, "5 DUP *\n ok\n");
        eq_u32("the line appears exactly once", count_sub((const char *)outbuf, "5 DUP *"), 1);
        eq_u32("the line executed once (25) and only once", tos(), 25);
        eq_u32("... with one cell on the stack", sp, 1);
    }
    {
        fresh();
        feeds("\x1d\x1d\r", 0); pump(64);
        eq_u32("escaped literal 0x1D survives the bridge, then the line discipline drops it",
               (u32)count_sub((const char *)outbuf, "\x1d"), 0);
        eq_str("... the empty line still answers ok", (const char *)outbuf, "\n ok\n");
    }

    printf("\nP10: %d passed, %d failed\n", passes, fails);
    return fails ? 1 : 0;
}
