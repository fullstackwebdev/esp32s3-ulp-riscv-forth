/* host_test.c — behavioural tests for the reference prototype (uforth.c).
 *
 * Build:  gcc -DHOST -std=c99 -Wall -Wextra -o uforth_test host_test.c && ./uforth_test
 *
 * The point of this file is to establish, by execution rather than by reading, (a) which
 * behaviours the prototype gets right, and (b) exactly how it fails when the Forth program
 * misbehaves. The "KNOWN DEFECT" cases assert the *current* wrong behaviour on purpose: they
 * are the failing-record, and the fix must flip them to a named error.
 */
#define main uforth_unused_main
#include "uforth.c"
#undef main

#include <stdio.h>
#include <string.h>

static int fails, passes;
static const char *group = "";

static void group_set(const char *g) { group = g; printf("\n== %s\n", g); }

static void check(int cond, const char *name, const char *detail)
{
    if (cond) { passes++; printf("  PASS  %s\n", name); }
    else { fails++; printf("  FAIL  %s   [%s] %s\n", name, group, detail ? detail : ""); }
}

static void eq_u32(const char *name, u32 got, u32 want)
{
    char buf[128];
    int cond = got == want;
    snprintf(buf, sizeof buf, "got 0x%08x (%d), want 0x%08x (%d)", got, (int32_t)got, want, (int32_t)want);
    check(cond, name, buf);
}

static void reset(void) { sp = 0; rsp = 0; errf = 0; wr32(V_STATE, 0); }
static void line(const char *s)
{
    size_t n = strlen(s);
    if (n >= TIBSZ) { printf("TEST BUG: line longer than TIBSZ: %s\n", s); fails++; return; }
    memcpy(tib, s, n); tl = (u8)n; ti = 0;
    interpret();
}
static u32 stack(int i) { return ds[i & (SD - 1)]; }
static u32 tos(void) { return ds[(sp - 1) & (SD - 1)]; }
static u32 nos(void) { return ds[(sp - 2) & (SD - 1)]; }

int main(void)
{
    boot_init();

    /* The prototype ships primitives only; DO/LOOP/IF/THEN are their runtime halves. The
     * boot layer below is the missing half, and loading it is itself a test of the model. */
    if (load("boot_min.fs")) { printf("FATAL: boot_min.fs failed to compile\n"); return 2; }
    printf("\n== boot layer\n");
    check(rd32(V_HERE) < 2048, "boot_min.fs fits in 2 KB", "");
    printf("  (info) dictionary at %u of %u bytes after boot\n", rd32(V_HERE), (unsigned)MEMSZ);

    group_set("arithmetic and stack primitives");
    reset(); line("1 2 +");
    check(sp == 1, "add leaves one cell", "");
    eq_u32("1 2 + = 3", tos(), 3);

    reset(); line("5 DUP *");
    eq_u32("5 DUP * = 25", tos(), 25);

    reset(); line("1 2 3 ROT");
    check(sp == 3 && stack(0) == 2 && stack(1) == 3 && stack(2) == 1, "1 2 3 ROT -> 2 3 1", "");

    reset(); line("10 3 U/MOD");
    eq_u32("U/MOD remainder", nos(), 1);
    eq_u32("U/MOD quotient", tos(), 3);

    group_set("division edge cases");
    reset(); line("-7 2 /MOD");
    eq_u32("-7 2 /MOD remainder", nos(), (u32)-1);
    eq_u32("-7 2 /MOD quotient", tos(), (u32)-3);

    /* Truncating division must not trap on INT_MIN / -1; RISC-V defines quotient = INT_MIN. */
    reset(); line("-2147483648 -1 /MOD");
    eq_u32("INT_MIN -1 /MOD remainder", nos(), 0);
    eq_u32("INT_MIN -1 /MOD quotient", tos(), 0x80000000u);

    reset(); line("7 0 /MOD");
    eq_u32("divide by zero remainder (Forth-level rule, not RISC-V's all-ones)", nos(), 0);
    eq_u32("divide by zero quotient (Forth-level rule)", tos(), 0);

    group_set("compiler and control flow");
    reset(); line(": T 3 0 DO I LOOP ;");
    check(!errf, ": T compiles", "");
    reset(); line("T");
    check(sp == 3, "T pushes 3 indices", "");
    eq_u32("T[0]", stack(0), 0);
    eq_u32("T[1]", stack(1), 1);
    eq_u32("T[2]", stack(2), 2);

    reset(); line(": N 2 0 DO 3 0 DO J LOOP LOOP ;");
    reset(); line("N");
    check(sp == 6, "nested loops push 6 J values", "");
    eq_u32("J first three", stack(0), 0);
    eq_u32("J fourth", stack(3), 1);
    eq_u32("J last", stack(5), 1);

    reset(); line(": DN 0 5 DO I -1 +LOOP ;");
    reset(); line("DN");
    printf("  (info) +LOOP descending pushed %u values: ", sp);
    for (int i = 0; i < sp; i++) printf("%u ", stack(i));
    printf("\n");
    check(sp == 6, "+LOOP -1 from 5 down over limit 0 runs 6 times", "");

    reset(); line(": G DUP 0> IF 111 ELSE 222 THEN ;");
    reset(); line("5 G");
    check(sp == 2 && tos() == 111, "IF taken", "");
    reset(); line("-5 G");
    check(sp == 2 && tos() == 222, "ELSE taken", "");

    /* NB: 1+ consumes and replaces the counter, so the loop ends holding 5 and nothing else.
     * The first version of this test asserted sp==5 — the test was wrong, not the Forth. */
    reset(); line(": CNT 0 BEGIN 1+ DUP 5 = UNTIL ;");
    reset(); line("CNT");
    check(sp == 1 && tos() == 5, "BEGIN/UNTIL runs until the flag", "");

    reset(); line(": WR 0 BEGIN DUP 3 < WHILE 1+ REPEAT ;");
    reset(); line("WR");
    check(tos() == 3, "WHILE/REPEAT", "");

    reset(); line(": Z 7 ;");
    reset(); line("' Z EXECUTE");
    eq_u32("' Z EXECUTE", tos(), 7);

    reset(); line(": Y ['] DUP ;");
    reset(); line("5 Y EXECUTE");
    check(sp == 2 && tos() == 5 && nos() == 5, "['] + EXECUTE duplicates", "");

    reset(); line(": A 1 ; : B A A + ;");
    reset(); line("B");
    eq_u32("nested colon words", tos(), 2);

    group_set("definers");
    reset(); line("CREATE XV 42 ,");
    reset(); line("XV @");
    eq_u32("CREATE + , + @", tos(), 42);

    reset(); line("99 CONSTANT C99");
    reset(); line("C99");
    eq_u32("CONSTANT", tos(), 99);

    reset(); line("CREATE YB 1 C, 2 C,");
    reset(); line("YB C@");
    reset(); line("YB 1 + C@");
    eq_u32("byte array second byte", tos(), 2);

    group_set("number base");
    wr32(V_BASE, 16);
    reset(); line("FF");
    eq_u32("hex FF", tos(), 255);
    wr32(V_BASE, 10);
    reset(); line("255");
    eq_u32("decimal 255", tos(), 255);

    group_set("error handling and rollback");
    reset(); line(": OK1 42 ;");
    u32 here_before = rd32(V_HERE), latest_before = rd32(V_LATEST);
    reset(); line(": BAD NOSUCHWORD ;");
    check(errf == 1, "undefined word inside a definition fails loudly", "");
    eq_u32("dictionary pointer rolled back (HERE)", rd32(V_HERE), here_before);
    eq_u32("latest header rolled back (LATEST)", rd32(V_LATEST), latest_before);
    eq_u32("compile state cleared", rd32(V_STATE), 0);
    reset(); line("OK1");
    eq_u32("previously defined word still works", tos(), 42);

    /* GUARDRAIL: partial definitions of CREATE/CONSTANT/." are not rolled back — only ':' is.
     * Without this test, a failed talked-about "rollback" looks complete when it is not. */
    reset();
    here_before = rd32(V_HERE);
    line("CREATE");                       /* no name -> err(), but HERE is untouched */
    check(errf == 1, "CREATE without a name fails", "");
    eq_u32("CREATE without a name does not move HERE", rd32(V_HERE), here_before);

    group_set("KNOWN DEFECTS — silent failure modes (asserting today's wrong behaviour)");
    /* GUARDRAIL: P() maps every out-of-range address onto one shared byte. A wild pointer is
     * therefore not an error but a wrong answer, which is how memory-corruption bugs hide. */
    /* 12288 > MEMSZ: the address is out of range, and the literal parser is base-10 only,
     * so hex must be written as a number or after "HEX". */
    reset(); line("12288 @");
    check(sp == 1 && !errf, "DEFECT: out-of-range read is accepted silently", "");
    reset(); line("7 12288 C!");
    check(!errf, "DEFECT: out-of-range byte write is accepted silently", "");
    reset(); line("12288 C@");
    eq_u32("DEFECT: out-of-range byte read back", tos(), 7);
    reset(); line("16384 C@");
    eq_u32("DEFECT: every out-of-range address aliases one shared junk byte", tos(), 7);

    /* GUARDRAIL: sp is u8 and the stack index is masked with SD-1, so the 17th push overwrites
     * cell 0 with no error. Depth must be checked before the store, or the stack must trap. */
    reset();
    line("1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20");
    check(sp == 20 && !errf, "DEFECT: 20 pushes into a 16-deep stack raise nothing", "");
    eq_u32("DEFECT: cell 0 was overwritten by the 17th push", stack(0), 17);

    /* GUARDRAIL: POP() on an empty stack wraps --sp from 0 to 255 and reads a stale cell —
     * underflow is invisible and produces plausible numbers. */
    reset(); line("+");
    check(!errf && sp == 255, "DEFECT: underflowing + is silent and wraps sp", "");

    /* GUARDRAIL: ' is not immediate, so inside a definition it compiles a call that parses at
     * runtime. Use ['] for compile-time behaviour, and make ' immediate or document the trap. */
    reset(); line(": Q ' ;");
    check(!errf, "DEFECT: ' inside a colon definition compiles without complaint", "");
    reset(); line("Q");
    check(errf == 1, "DEFECT: ... and then explodes at runtime, not at compile time", "");

    /* GUARDRAIL: the terminal input buffer is 80 bytes and load() rejects longer lines, but the
     * interactive path (forth_quit) silently drops characters past TIBSZ-1. boot_min.fs itself
     * tripped this on its first line, so the limit is real, not theoretical. */
    /* The file loader is loud ("line too long"), but interpret() itself has no line-length
     * knowledge: a 79-character token is simply one token. Truncation happens earlier, in
     * forth_quit's character loop, and is verified at the shell level (see REVIEW-RUN.txt). */
    reset();
    {
        char long_tok[TIBSZ];
        memset(long_tok, '1', TIBSZ - 1);
        long_tok[TIBSZ - 1] = 0;
        line(long_tok);
        printf("  (info) 79-digit token parsed as one number, sp=%u\n", sp);
        check(sp == 1, "DEFECT: a 79-digit token is one huge number, no overflow check", "");
    }

    /* GUARDRAIL: KEY? goes through pl_hw(5,...) and the host backend has no case 5, so the
     * non-blocking input path is untested on the host while looking implemented. */
    reset(); line("KEY?");
    eq_u32("DEFECT: KEY? is hardwired false on the host", tos(), 0);

    printf("\n%d passed, %d failed\n", passes, fails);
    return fails ? 1 : 0;
}
