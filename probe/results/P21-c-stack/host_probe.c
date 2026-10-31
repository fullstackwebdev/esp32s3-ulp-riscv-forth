/* host_probe.c - P21 runtime cross-check of the static .su chain on the host build.
 *
 * The engine is #included (interpret() is static), the same trick ulp_stubs.c and host_test.c use.
 * -finstrument-functions makes GCC call __cyg_profile_func_enter(fn, caller) on entry to every
 * instrumented function, so the hook sees a stack address *inside the callee's frame*. Recording
 * the minimum such address across a workload, and the address seen on entry to main, gives
 * main_sp - deepest_sp = the frames the workload actually pushed.
 *
 * GUARDRAIL: the recorded address is the hook's own local, not the callee's sp — but the hook frame
 * is identical for every call, so it cancels in the difference; comparing a hook address against a
 * raw &local in main would be off by the hook frame and would understate the chain by ~30 B. —
 * both endpoints must come from the same hook.
 * GUARDRAIL: the hook must never be instrumented itself (no_instrument_function), otherwise every
 * entry recurses once more and the reported depth grows with the call count, not the call depth.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <dlfcn.h>

#define main uforth_unused_main
#define HOST 1              /* the engine's boot_init()/loaders live behind #ifdef HOST */
#include "uforth.c"
#undef main

/* ---- stack-depth recorder ---- */
static char *g_lo;            /* lowest address seen since reset */
static const void *g_lo_fn;   /* function that reached it */
static char *g_main_addr;     /* address reported on entry to main */
static int g_armed;

/* GUARDRAIL: main() is not declared yet where the hook is defined, so it cannot be compared to
 * fn directly; a constructor runs before main, and the first instrumented entry after it *is*
 * main — taking &main any other way (a helper call) adds that helper's frame to the delta. */
__attribute__((constructor, no_instrument_function))
static void arm(void) { g_armed = 1; }

__attribute__((no_instrument_function))
void __cyg_profile_func_enter(void *fn, void *caller)
{
    char here;
    (void)caller;
    if (!g_lo || &here < g_lo) { g_lo = &here; g_lo_fn = fn; }
    if (g_armed && !g_main_addr) g_main_addr = &here;
}
__attribute__((no_instrument_function))
void __cyg_profile_func_exit(void *fn, void *caller) { (void)fn; (void)caller; }

static void reset_probe(void) { g_lo = 0; g_lo_fn = 0; }

static void line(const char *s)
{
    size_t n = strlen(s);
    if (n >= TIBSZ) { fprintf(stderr, "line too long\n"); exit(2); }
    memcpy(tib, s, n); tl = (u8)n; ti = 0;
    interpret();
    if (errf) fprintf(stderr, "  (error flag set on: %s)\n", s);
}

static int load_file(const char *file)
{
    char buf[256]; FILE *f = fopen(file, "r");
    if (!f) { fprintf(stderr, "cannot open %s\n", file); return 1; }
    while (fgets(buf, sizeof buf, f)) {
        size_t n = strlen(buf);
        while (n && (buf[n - 1] == '\n' || buf[n - 1] == '\r')) n--;
        if (!n || n >= TIBSZ) continue;
        memcpy(tib, buf, n); tl = (u8)n; ti = 0;
        interpret();
        if (errf) { fprintf(stderr, "boot line failed: %s\n", buf); fclose(f); return 1; }
    }
    fclose(f);
    return 0;
}

int main(int argc, char **argv)
{
    static const char *w[][2] = {
        { "primitive",   "1 2 +" },              /* run(): dispatch + PUSH/POP        */
        { "literal",     "lit42" },              /* run(): LIT reads rd32_paged(ip)   */
        { "colon call",  "sq" },                 /* DOCOL -> body -> EXIT             */
        { "branch",      "br" },                 /* 0BRANCH taken (flag = 0)          */
        { "page fault",  "3 fetch" },            /* @ -> rd32_paged -> pg_load -> rd8 */
    };
    unsigned i;

    boot_init();
    if (argc > 1 && load_file(argv[1])) return 1;   /* optional boot_min.fs */
    /* GUARDRAIL: boot_min.fs emits 16-bit tokens with W,/W!, so its IF/THEN produce 2-byte
     * operands and silently misbranch in this 32-bit build — compile the 0BRANCH body with the
     * 32-bit "," primitive instead of trusting the 16-bit boot layer. */
    line(": 0BR, ['] 0BRANCH , 0 , ; IMMEDIATE");
    line(": lit42 42 ;");
    line(": sq DUP * ;");
    line(": br 0 0BR, ;");
    line(": fetch @ ;");

    fprintf(stderr, "# main hook address %p\n", (void *)g_main_addr);
    fprintf(stderr, "%-12s %10s %10s  %s\n", "workload", "delta B", "addr", "deepest fn");
    for (i = 0; i < sizeof w / sizeof w[0]; i++) {
        char *m = g_main_addr;
        reset_probe();
        line(w[i][1]);
        Dl_info di;
        const char *nm = (g_lo_fn && dladdr(g_lo_fn, &di) && di.dli_sname) ? di.dli_sname : "?";
        fprintf(stderr, "%-12s %10ld %10p  %-8s %p\n", w[i][0], (long)(m - g_lo), (void *)g_lo, nm, g_lo_fn);
    }
    return 0;
}
