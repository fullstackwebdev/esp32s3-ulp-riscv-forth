/* measure.c - P02: dictionary density and page straddles for one token width.
 *
 * Build: gcc -DHOST -std=c99 -Wall -Wextra -o measure measure.c
 * Run:   timeout 60 ./measure boot_min.fs corpus_extra.fs
 *
 * GUARDRAIL: this harness must be built with a MEMSZ large enough for the 32-bit build's
 * dictionary (the corpus needs ~2.6 KB there, over the default 2560). P() maps every address
 * past MEMSZ onto one shared junk byte, so an overflow is not an error: bodies read back as
 * zeros and the literal census silently reports 0 rather than failing. -DMEMSZ=8192 on both
 * builds; MEMSZ affects only the bounds check in P(), never a size or an address.
 *
 * This file is byte-identical for build A (16-bit tokens) and build B (32-bit xts); only
 * uforth.c and boot_min.fs differ, so every number below is produced by the same code path.
 * It compiles the corpus exactly like host_test.c does (load() -> interpret(), one line at a
 * time) and records, for every colon definition, where its header starts, where its code field
 * (the xt) is, and where HERE stood after ';'.
 */
#define main uforth_unused_main
#include "uforth.c"
#undef main

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAXDEF 512

/* GUARDRAIL: token width cannot be inferred reliably at run time (header sizes vary with the
 * name), so it is a -D that must match the build under test; guessing it here silently
 * decodes every body at the wrong stride and "proves" a layout that does not exist. */
#ifndef TOKW
#define TOKW 2
#endif
#define ALIGNW(x) (((x) + (TOKW - 1)) & ~(u32)(TOKW - 1))

typedef struct { char name[40]; u32 start, xt, end; int boot; } Def;
static Def defs[MAXDEF];
static int ndef;
static u32 prim_end;                  /* HERE after boot_init: the primitive headers */
static u32 dict_start;                /* DICT: page origin for the "from DICT" count */
static const char *dump_name;         /* -d NAME: print one body token by token */

/* copy the n-th (0-based) blank-delimited token of line into out, upper-cased like word() */
static int tok(const char *line, int n, char *out, size_t cap)
{
    size_t i = 0;
    while (line[i]) {
        while (line[i] == ' ' || line[i] == '\t') i++;
        if (!line[i]) return 0;
        if (n == 0) {
            size_t k = 0;
            while (line[i] > ' ' && k + 1 < cap) {
                char c = line[i++];
                if (c >= 'a' && c <= 'z') c -= 32;
                out[k++] = c;
            }
            out[k] = 0;
            return 1;
        }
        while (line[i] > ' ') i++;
        n--;
    }
    return 0;
}

/* GUARDRAIL: definitions are found by watching STATE, not by scanning for ';', because a
 * corpus definition may span several lines (the 20-token word does) and ';' also appears
 * inside ." text — matching on text counts one definition twice or merges two into one. */
static void load_corpus(const char *file, int boot)
{
    char line[300], t[40];
    FILE *f = fopen(file, "r");
    int open = 0;
    if (!f) { printf("CANNOT-OPEN %s\n", file); exit(1); }
    while (fgets(line, sizeof line, f)) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r')) n--;
        /* GUARDRAIL: TIBSZ is 80 and load() rejects a longer line outright; truncating here
         * instead would measure a different program than the one that ships. */
        if (n >= TIBSZ) { printf("LINE-TOO-LONG %s\n", file); exit(1); }
        if (!open && rd32(V_STATE) == 0 && tok(line, 0, t, sizeof t) && !strcmp(t, ":")) {
            if (ndef >= MAXDEF) { printf("TOO-MANY-DEFS\n"); exit(1); }
            if (!tok(line, 1, defs[ndef].name, sizeof defs[ndef].name)) {
                printf("UNNAMED-DEF %s\n", file); exit(1);
            }
            defs[ndef].start = rd32(V_HERE);
            defs[ndef].boot = boot;
            open = 1;
        }
        memcpy(tib, line, n); tl = (u8)n; ti = 0;
        interpret();
        if (errf) { printf("COMPILE-ERROR %s: %s\n", file, line); exit(1); }
        if (open && rd32(V_STATE) == 0) {
            Def *d = &defs[ndef];
            u8 imm = 0, i, ln = (u8)strlen(d->name);
            d->end = rd32(V_HERE);
            wr8(PAD, ln);
            for (i = 0; i < ln; i++) wr8(PAD + 1 + i, (u8)d->name[i]);
            d->xt = find(ln, &imm);          /* body start, from the dictionary itself */
            if (!d->xt || d->xt >= d->end) { printf("BAD-XT %s\n", d->name); exit(1); }
            ndef++;
            open = 0;
        }
        /* GUARDRAIL: this check must run only with STATE=0 and no definition open: IF leaves
         * its branch placeholder on the data stack and THEN pops it, so a definition split
         * across lines legitimately holds a non-empty stack in between and a mid-definition
         * check reports a false "stack not empty". */
        if (!open && rd32(V_STATE) == 0 && sp != 0) {
            printf("STACK-NOT-EMPTY %s: %s\n", file, line); exit(1);
        }
    }
    if (open) { printf("UNTERMINATED-DEF in %s\n", file); exit(1); }
    fclose(f);
}

static u32 align4(u32 a) { return (a + 3) & ~3u; }

/* body census: how many emitted body bytes are literal operands, branch operands and inline
 * strings. This is what says whether a 2-byte "small literal" encoding is worth the work. */
typedef struct { u32 body, lits, litbytes, branches, brbytes, strs, strbytes; } Census;

/* GUARDRAIL: resolve opcode xts through find(), never by re-deriving the header size here —
 * the header's code field is padded to the token width, and a hand-rolled offset silently
 * returns the previous word's xt, so every token is classified as "plain call" and the literal
 * census comes out as zero. */
static u32 xt_of(const char *name)
{
    u8 imm = 0, i, ln = (u8)strlen(name);
    wr8(PAD, ln);
    for (i = 0; i < ln; i++) wr8(PAD + 1 + i, (u8)name[i]);
    return find(ln, &imm);
}

static Census census(int from, int to)
{
    Census c; int i;
    u32 xlit = xt_of("LIT"), xbr = xt_of("BRANCH"), xzbr = xt_of("0BRANCH"),
        xloop = xt_of("(LOOP)"), xploop = xt_of("(+LOOP)"), xstr = xt_of("(.\")");
    memset(&c, 0, sizeof c);
    if (!xlit || !xbr || !xzbr || !xloop || !xploop || !xstr) {
        printf("OPCODE-NOT-FOUND\n"); exit(1);
    }
    for (i = from; i < to; i++) {
        u32 a = defs[i].xt, end = defs[i].end;
        c.body += end - a;
        while (a + TOKW <= end) {
            u32 t = (TOKW == 2) ? rd16(a) : rd32(a);
            if (t == xlit) { c.lits++; c.litbytes += 2 * TOKW; a += 2 * TOKW; }
            else if (t == xbr || t == xzbr || t == xloop || t == xploop) {
                c.branches++; c.brbytes += 2 * TOKW; a += 2 * TOKW;
            } else if (t == xstr) {
                u32 blob = ALIGNW(rd8(a + TOKW) + 1);
                c.strs++; c.strbytes += TOKW + blob; a += TOKW + blob;
            } else a += TOKW;
        }
        /* a body that does not decode exactly to HERE means the layout and the interpreter
         * disagree; that is a finding, not noise, so it is printed rather than swallowed */
        if (a != end) printf("DECODE-MISMATCH %s a=%u end=%u\n", defs[i].name, a, end);
    }
    return c;
}

/* print one definition's body as raw cells: cheap proof that the decoder and the interpreter
 * agree about where token boundaries are, per build. */
static void dump_body(int i)
{
    u32 a = defs[i].xt, xlit = xt_of("LIT"), xbr = xt_of("BRANCH"), xzbr = xt_of("0BRANCH"),
        xloop = xt_of("(LOOP)"), xploop = xt_of("(+LOOP)"), xstr = xt_of("(.\")");
    printf("DUMP %s xt=%u end=%u:", defs[i].name, a, defs[i].end);
    while (a + TOKW <= defs[i].end) {
        u32 t = (TOKW == 2) ? rd16(a) : rd32(a);
        printf(" %u@%u", t, a);
        if (t == xlit || t == xbr || t == xzbr) a += 2 * TOKW;
        else if (t == xloop || t == xploop) a += 2 * TOKW;
        else if (t == xstr) a += TOKW + ALIGNW(rd8(a + TOKW) + 1);
        else a += TOKW;
    }
    printf("\n");
}

/* does [s,e) cross a page boundary at origin + k*page? */
static int straddles(u32 s, u32 e, u32 origin, u32 page)
{
    if (e <= s) return 0;
    return ((s - origin) / page) != ((e - 1 - origin) / page);
}

typedef struct { u32 words, bytes, bodysum, maxbytes, maxbody, over512b, over512d; } Stat;

static Stat stats(int from, int to)
{
    Stat st; int i;
    memset(&st, 0, sizeof st);
    for (i = from; i < to; i++) {
        u32 sz = defs[i].end - defs[i].start, body = defs[i].end - defs[i].xt;
        st.words++; st.bytes += sz; st.bodysum += body;
        if (sz > st.maxbytes) st.maxbytes = sz;
        if (body > st.maxbody) st.maxbody = body;
        if (body > 512) st.over512b++;
        if (sz > 512) st.over512d++;
    }
    return st;
}

/* straddle counts: real layout, and an idealised repack at 4-byte alignment from the same
 * origin (the layout the page rule would have to cope with if every definition were packed
 * tightly). */
static void straddle_counts(int from, int to, u32 page, u32 *actual0, u32 *actualD,
                            u32 *pack0, u32 *packD)
{
    u32 cursor = align4(dict_start); int i;
    *actual0 = *actualD = *pack0 = *packD = 0;
    for (i = from; i < to; i++) {
        u32 sz = defs[i].end - defs[i].start;
        u32 ps = align4(cursor), pe = ps + sz;
        *actual0 += straddles(defs[i].start, defs[i].end, 0, page);
        *actualD += straddles(defs[i].start, defs[i].end, dict_start, page);
        *pack0 += straddles(ps, pe, 0, page);
        *packD += straddles(ps, pe, dict_start, page);
        cursor = pe;
    }
}

static void report(const char *label, int from, int to)
{
    Stat st = stats(from, to);
    u32 a0, aD, p0, pD, b0, bD, q0, qD;
    if (!st.words) return;
    straddle_counts(from, to, 512, &a0, &aD, &p0, &pD);
    straddle_counts(from, to, 256, &b0, &bD, &q0, &qD);
    printf("GROUP %s words=%u bytes=%u mean=%.2f max=%u bodymean=%.2f bodymax=%u "
           "over512body=%u over512def=%u\n",
           label, st.words, st.bytes, (double)st.bytes / st.words, st.maxbytes,
           (double)st.bodysum / st.words, st.maxbody, st.over512b, st.over512d);
    printf("STRADDLE512 %s actual@0=%u actual@DICT=%u pack4@0=%u pack4@DICT=%u\n",
           label, a0, aD, p0, pD);
    printf("STRADDLE256 %s actual@0=%u actual@DICT=%u pack4@0=%u pack4@DICT=%u\n",
           label, b0, bD, q0, qD);
    {
        Census c = census(from, to);
        printf("CENSUS %s body=%u lits=%u litbytes=%u branches=%u brbytes=%u strs=%u "
               "strbytes=%u\n", label, c.body, c.lits, c.litbytes, c.branches, c.brbytes,
               c.strs, c.strbytes);
    }
}

int main(int argc, char **argv)
{
    int i, nb = 0;
    boot_init();
    prim_end = rd32(V_HERE);
    dict_start = DICT;
    /* argv[1] = boot layer, argv[2..] = corpus: exactly what "same corpus" means here */
    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-d")) { dump_name = argv[++i]; continue; }
        load_corpus(argv[i], i == 1 && i < 2);
        if (i == 1) nb = ndef;
    }
    printf("PRIMS bytes=%u\n", prim_end - dict_start);
    if (dump_name)
        for (i = 0; i < ndef; i++) if (!strcmp(defs[i].name, dump_name)) dump_body(i);
    for (i = 0; i < ndef; i++) {
        Census c = census(i, i + 1);
        printf("DEF %-8s start=%u xt=%u end=%u size=%u body=%u lits=%u\n", defs[i].name,
               defs[i].start, defs[i].xt, defs[i].end,
               defs[i].end - defs[i].start, defs[i].end - defs[i].xt, c.lits);
    }
    printf("TOTAL bytes=%u words=%u here=%u\n", rd32(V_HERE) - dict_start, ndef, rd32(V_HERE));
    report("boot", 0, nb);
    report("extra", nb, ndef);
    report("all", 0, ndef);
    return 0;
}
