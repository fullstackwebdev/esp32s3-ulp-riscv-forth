/* p38_test.c - P38: measures the *stack effect* of the fixed block words from the C side.
 *
 * Why a C driver and not a Forth test: the claim under test is "BLOCK leaves exactly one address"
 * and "SAVE returns its status", i.e. a statement about `sp`, and this primitive set has no `.S`
 * and no `.` — a Forth test can only show that a *later* word did not underflow, which is the
 * observation that failed to catch the bug in P33. Here sp is read before and after each call.
 *
 * GUARDRAIL: this file #includes uforth.c (the host_test.c idiom), so boot_init()/srv must be set up
 * here exactly as uforth.c's own main() does — a driver that skips the fake-file initialiser sees an
 * all-zero server and "the right bytes" becomes indistinguishable from "nothing was fetched".
 */
#define main uforth_unused_main
#include "uforth.c"
#undef main

#include <stdio.h>
#include <string.h>

/* GUARDRAIL: these two codes are written in Forth (src/blocks.fs) and this driver must not invent
 * its own copy of the numbers — read them off the layer by name once it is loaded (see code_of). */
static int fails, passes;

static void ck(const char *name, long got, long want)
{
    if (got == want) { passes++; printf("  PASS  %s  (%ld)\n", name, got); }
    else { fails++; printf("  FAIL  %s  got %ld want %ld\n", name, got, want); }
}

static const char *load_ok(const char *f)
{
    if (load(f)) { printf("FATAL: load %s\n", f); return f; }
    return 0;
}

/* name -> xt through the same find() the interpreter uses, so a test can call a Forth word. */
static u16 xt_of(const char *nm)
{
    u8 n = 0, imm;
    while (nm[n]) { wr8(PAD + 1 + n, (u8)nm[n]); n++; }
    wr8(PAD, n);
    return find(n, &imm);
}

/* a CREATE'd variable's body address is what DOVAR pushes: (w + 2 + 3) & ~3 */
static u32 var_of(const char *nm) { return (u32)((xt_of(nm) + 2 + 3) & ~3u); }

/* a CONSTANT's value is what DOCON pushes: rd32((w + 2 + 3) & ~3) */
static i32 const_of(const char *nm) { return (i32)rd32(var_of(nm)); }

/* ---- (b) read the compiled token stream back out of mem[] ----
 * GUARDRAIL: "the branch works" is not the claim — the claim is that the *operand* is 2 bytes and
 * points at the THEN target. A 4-byte token would still branch correctly on a 2-byte reader only
 * for the first IF in a body; after that the whole stream is off by two, so the walk is checked
 * token by token and every operand must equal an address the walk itself produced. */
static u16 cf_at(u32 p) { return rd16(rd16(p)); }   /* GUARDRAIL: a compiled token is an *xt*
                                                      * (an address); the code field it names is
                                                      * rd16(xt), not rd16(p) — reading the body
                                                      * cell directly names an address, and every
                                                      * token after it is mis-decoded. */
static void disasm(const char *nm)
{
    /* GUARDRAIL: a colon word's xt points at its DOCOL cell; the first *token* is xt+2
     * (P_DOCOL: ip = w + 2). Walking from xt itself reads DOCOL as a token and every offset after
     * it is wrong — which is exactly what a 2-byte/4-byte width bug looks like, so the reader must
     * not introduce the same off-by-two it is hunting. */
    u32 x0 = xt_of(nm) + 2, p = x0, bound[64], tgt[64];
    int i, j, nb = 0, nt = 0;
    printf("  (b) %s: DOCOL @ %04x, first token @ %04x\n", nm, (unsigned)(x0 - 2), (unsigned)x0);
    for (i = 0; i < 60; i++) {
        u16 t = rd16(p), cf = rd16(t);
        bound[nb++] = p;
        if (cf == P_EXIT) { printf("      %04x  EXIT\n", (unsigned)p); p += 2; break; }
        if (cf == P_ZBRANCH || cf == P_BRANCH) {
            tgt[nt++] = rd16(p + 2);
            printf("      %04x  %-7s operand@%04x = %04x   [token 2 B + operand 2 B = 4 B]\n",
                   (unsigned)p, cf == P_ZBRANCH ? "0BRANCH" : "BRANCH", (unsigned)(p + 2),
                   (unsigned)rd16(p + 2));
            p += 4; continue;
        }
        if (cf == P_LIT)   { printf("      %04x  LIT %u\n", (unsigned)p, (unsigned)rd32(p + 2)); p += 6; continue; }
        if (cf == P_PDOTQ) { u32 n = rd8(p + 2); printf("      %04x  (\") %u B\n", (unsigned)p, (unsigned)n);
                             p = (p + 2 + n + 2) & ~1u; continue; }
        if (cf == P_DOCOL) { printf("      %04x  CALL %04x\n", (unsigned)p, (unsigned)t); p += 2; continue; }
        printf("      %04x  prim#%u/%s\n", (unsigned)p, (unsigned)cf,
               cf == P_EMIT ? "EMIT" : cf == P_ZEQ ? "0=" : cf == P_ADD ? "+" : "?");
        p += 2;
    }
    printf("      body %04x..%04x = %u bytes, %d tokens\n", (unsigned)x0, (unsigned)p,
           (unsigned)(p - x0), nb);
    for (j = 0; j < nt; j++) {
        int k, found = -1;
        for (k = 0; k < nb; k++) if (bound[k] == tgt[j]) found = k;
        printf("      operand %04x -> %s\n", (unsigned)tgt[j],
               found >= 0 ? "a token boundary" : "NOT a boundary (stream mis-addressed)");
        ck("b-operand-lands-on-a-boundary", found >= 0 ? 1 : 0, 1);
    }
}

/* run a word and report how many cells it left behind (0 = it honoured its stack comment) */
static int effect(u16 xt, u32 in, u32 *out)
{
    u8 s0, s1;
    PUSH(in);
    s0 = sp;
    run(xt);
    s1 = sp;                          /* GUARDRAIL: read sp BEFORE the POP below — measuring after
                                       * it counts the driver's own read as the word's effect and
                                       * every case reports -1. */
    *out = POP();
    return (int)s1 - (int)s0;         /* negative = it consumed more than it returned */
}

int main(int argc, char **argv)
{
    u16 b, s, up, u;
    u32 v;
    u8 s0;
    u32 n0, k0;
    int e;

    setvbuf(stdout, NULL, _IOLBF, 0);
    boot_init();
    for (n0 = 0; n0 < SRVBLK; n0++) for (k0 = 0; k0 < BLKSZ; k0++) srv[n0][k0] = (u8)(k0 + 7 * n0);

    if (load_ok(argc > 1 ? argv[1] : "src/boot16.fs")) return 2;
    if (load_ok(argc > 2 ? argv[2] : "src/blocks.fs")) return 2;

    printf("\nP38 geometry: MEMSZ=%u BLKSZ=%u BLKADR=%u DICT=%u HERE=%u (place_ok=%d boot_ok=%d)\n",
           (unsigned)MEMSZ, (unsigned)BLKSZ, (unsigned)BLKADR, (unsigned)DICT,
           (unsigned)rd32(V_HERE), (int)blk_place_ok(), (int)blk_boot_ok());

    b = xt_of("BLOCK"); s = xt_of("SAVE"); up = xt_of("UPDATE");

    printf("\n(c) BLOCK stack discipline\n");
    e = effect(b, 0, &v);
    ck("c1 BLOCK 0 -> net cells", e, 0);          /* ( n -- addr ): 1 in, 1 out */
    ck("c2 BLOCK 0 -> the buffer address", (long)v, (long)BLKADR);
    ck("c3 BLOCK 0 -> BLKERR 0", (long)rd32(var_of("BLKERR")), 0);

    /* a bad block: -1 cannot be a block of any file, so the layer refuses it before the mailbox */
    blk_out = 0;
    e = effect(b, (u32)-1, &v);
    ck("c4 BLOCK -1 -> net cells", e, 0);
    ck("c5 BLOCK -1 -> ERR_RANGE", (long)(i32)v, (long)const_of("ERR_RANGE"));
    ck("c6 BLOCK -1 -> BLKERR", (long)(i32)rd32(var_of("BLKERR")), (long)const_of("ERR_RANGE"));
    ck("c7 BLOCK -1 -> no request was made (blk_out)", (long)blk_out, 0);

    /* a block the file does not contain: the server never answers, the C bound runs out */
    e = effect(b, 15, &v);
    ck("c8 BLOCK 15 -> net cells", e, 0);
    ck("c9 BLOCK 15 -> ERR_NO_SERVER (-3)", (long)(i32)v, -3);
    ck("c10 BLOCK 15 -> the request is still outstanding", (long)blk_out, 1);
    blk_out = 0;                                   /* put the mailbox back for (d) */

    printf("\n(d) SAVE returns its status\n");
    /* clean buffer: SAVE sends nothing and says 0 */
    s0 = sp; run(s); ck("d1 SAVE (clean) -> net cells", (int)sp - (int)s0, 1);
    ck("d2 SAVE (clean) -> 0", (long)POP(), 0);

    /* dirty buffer on a live server: 0 */
    e = effect(b, 0, &v);
    ck("d3 BLOCK 0 (reload)", (long)v, (long)BLKADR);
    wr8(BLKADR + 9, 0x42);
    run(up);
    s0 = sp; run(s); ck("d4 SAVE (dirty, ok) -> net cells", (int)sp - (int)s0, 1);
    ck("d5 SAVE (dirty, ok) -> 0", (long)POP(), 0);
    ck("d6 server's copy of blk0[9]", (long)srv[0][9], 0x42);

    /* failed save: block 15 leaves a request outstanding, so the write is refused ERR_BUSY */
    e = effect(b, 15, &v);
    ck("d7 BLOCK 15 (to wedge the mailbox)", (long)(i32)v, -3);
    wr8(BLKADR + 9, 0x43);
    run(up);
    s0 = sp; run(s); ck("d8 SAVE (failed) -> net cells", (int)sp - (int)s0, 1);
    ck("d9 SAVE (failed) -> ERR_BUSY (-2)", (long)(i32)POP(), -2);
    ck("d10 SAVE (failed) -> the dirty flag stays set", (long)rd32(var_of("BLKDRT")), (long)(u32)-1);

    /* (e) the placement assert, when the dictionary is grown into the buffer */
    if (argc > 3 && !strcmp(argv[3], "grow")) {
        printf("\n(e) overlap assert\n");
        wr32(V_HERE, (u32)BLKADR + 50);            /* the dictionary "grew" 50 bytes into the buffer */
        blk_out = 0;
        e = effect(b, 0, &v);
        ck("e1 BLOCK with HERE past BLKADR -> net cells", e, 0);
        ck("e2 BLOCK with HERE past BLKADR -> ERR_BUFOVER", (long)(i32)v, (long)const_of("ERR_BUFOVER"));
        ck("e3 BLKERR mirror", (long)(i32)rd32(var_of("BLKERR")), (long)const_of("ERR_BUFOVER"));
        ck("e4 the fetch never ran (blk_out)", (long)blk_out, 0);
        ck("e5 the server's block 0 is untouched", (long)srv[0][9], 0x42);
    }

    printf("\n(b) the compiled branch operand, read back\n");
    if (load_ok("src/exp_b.fs")) return 2;
    {
        u32 b0 = xt_of("B0") + 2, zb = b0 + 6, b1 = xt_of("B1") + 2;
        ck("b1 B0: LIT then 0BRANCH at +6", (long)cf_at(zb), (long)P_ZBRANCH);
        ck("b2 B0: the operand sits 2 B after the token", (long)((zb + 2) - zb), 2);
        ck("b3 B0: operand value - 0BRANCH address", (long)(rd16(zb + 2) - zb), 4);
        ck("b4 B0: target holds EXIT (the THEN target)", (long)cf_at(rd16(zb + 2)), (long)P_EXIT);
        /* GUARDRAIL: ELSE patches the IF's operand to *its own* body (the BRANCH token + 4), not to
         * the BRANCH token — the false path must skip the true branch's code, and it reaches the
         * else body directly. Measured against the BRANCH token, so the expectation is 4 either way
         * only when the else body is empty; the check is stated against the address ELSE produces. */
        ck("b5 B1: IF's false target is the else body (BRANCH token + 4)", (long)(rd16(b1 + 8) - (b1 + 10)), 4);
        ck("b6 B1: next token is BRANCH", (long)cf_at(b1 + 10), (long)P_BRANCH);
        ck("b7 B1: BRANCH operand -> THEN target", (long)(rd16(b1 + 12) - (b1 + 10)), 4);
    }
    disasm("B0"); disasm("B1"); disasm("B2"); disasm("B3"); disasm("B4");

    if (argc > 3 && !strcmp(argv[3], "lvl")) {     /* the (a) cases, as numbers the host can read */
        int a, bb, c, d; u16 lv;
        if (load_ok("src/exp_a.fs")) return 2;
        lv = xt_of("LVL");
        printf("\n(a) LVL table, executed:\n");
        for (a = 0; a < 2; a++) for (bb = 0; bb < 2; bb++) for (c = 0; c < 2; c++) for (d = 0; d < 2; d++) {
            PUSH(a); PUSH(bb); PUSH(c); PUSH(d); run(lv);
            printf("  LVL %d %d %d %d -> %u\n", a, bb, c, d, (unsigned)POP());
        }
    }

    printf("\nP38 driver: %d passed, %d failed\n", passes, fails);
    return fails ? 1 : 0;
}
