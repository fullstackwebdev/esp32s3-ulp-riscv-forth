/* uforth.c - a tiny token-threaded Forth for the ESP32-S3 ULP-RISC-V core.
 *
 * PROVENANCE: this file is reproduced verbatim from the earlier prototype session so the
 * review in docs/03-prototype-review.md has something exact to point at. Do not "fix" it
 * here; fixes go in a copy, so the baseline stays comparable.
 *
 * - No libc, no malloc, no floating point.
 * - All Forth memory is one byte array, addressed by offsets (16-bit tokens).
 * - Only ~50 primitives are C. Everything else lives in boot.fs, which is
 *   compiled on a PC into image.h and baked into the ULP binary, so the
 *   chip never carries source text or dictionary names it does not need.
 *
 * Build modes
 *   make test          PC build: compiles boot.fs, runs the test files
 *   make image.h       dumps the compiled dictionary
 *   ULP build          compile with -DIMAGE (uses image.h), add ulp_main.c
 */
#include <stdint.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef int32_t i32;

#ifndef MEMSZ
#define MEMSZ 2560          /* bytes of Forth memory (dictionary + variables) */
#endif
#ifndef SD
#define SD 16               /* stack depth, cells, power of 2 (each stack costs 4*SD bytes) */
#endif
#ifndef TIBSZ
#define TIBSZ 80            /* terminal input buffer */
#endif

/* ---- platform hooks (implemented by the host build or ulp_main.c) ---- */
int  pl_key(void);                       /* blocking read of one character  */
void pl_emit(int c);                     /* write one character (may drop)  */
u32  pl_hw(int op, u32 a, u32 b);        /* 0 gpio_get 1 gpio_set 2 adc 3 ms 4 wake 5 key? */

/* ---- memory map: system variables live inside mem[] ---- */
/* GUARDRAIL: V_XLIT/V_XEXIT/V_XSTR hold xts, so they widen with the token width; PAD must
 * follow them or boot_init's saved xts are overwritten by the next parsed word — the symptom
 * is a crash inside ':' thousands of bytes later, not an error at the overwrite. */
enum { V_STATE = 0, V_HERE = 4, V_LATEST = 8, V_BASE = 12,
       V_XLIT = 16, V_XEXIT = 20, V_XSTR = 24,   /* xts the C code compiles (P02: 32-bit) */
       PAD = 28,                                  /* counted string, 32 bytes */
       DICT = 64 };

#ifdef IMAGE
#include "image.h"
#else
static u8 mem[MEMSZ];
#endif
static u8 junk;

static u8 *P(u32 a) { return a < MEMSZ ? mem + a : &junk; }  /* wild pointers are harmless */
static u8  rd8(u32 a)            { return *P(a); }
static void wr8(u32 a, u8 v)     { *P(a) = v; }
static u16 rd16(u32 a)           { return rd8(a) | (u16)rd8(a + 1) << 8; }
/* GUARDRAIL: with 32-bit tokens every dictionary cell is 4 bytes; a leftover 2-byte fetch does
 * not fault on the host, it silently returns half an xt and jumps into the middle of a body. */
static void wr16(u32 a, u16 v)   { wr8(a, v); wr8(a + 1, v >> 8); }
static u32 rd32(u32 a)           { return rd16(a) | (u32)rd16(a + 2) << 16; }
static void wr32(u32 a, u32 v)   { wr16(a, v); wr16(a + 2, v >> 16); }

/* ---- paging: 4 x 256 B frames + a 4-entry page table (P03e) ----
 * The design executes the dictionary out of page frames, not out of mem[], so every instruction-stream
 * read goes through resolve(). P12 only needs the call sites to be real and costed; the fault path is
 * stubbed (nothing is executed here — the image is linked and measured, never run).
 * GUARDRAIL: the frames and the table must be uninitialised static arrays, because only .bss stays out
 * of the ULP blob — adding an initialiser turns them into .data, which is copied into the blob and
 * inflates .bin by ~1040 B, the exact regression the brief asks us to disprove. */
#define NFRM 4
#define FRMB 256                     /* one dictionary page = one frame */
static u8  frm[NFRM][FRMB];          /* 1024 B, .bss */
static u32 ptab[NFRM];               /* 16 B, .bss; entry = virtual page + 1, 0 = frame empty */

/* Stub page-in: no LRU and no dirty write-back — frame 0 is always the victim. Real paging (P03e)
 * faults here; P12 must compile and cost the call site, not fault. */
static u32 pg_load(u32 pg)
{
    u32 f, i;
    for (f = 0; f < NFRM; f++) if (ptab[f] == pg + 1) return f;
    for (i = 0; i < FRMB; i++) frm[0][i] = rd8(pg * FRMB + i);
    ptab[0] = pg + 1;
    return 0;
}

/* GUARDRAIL: resolve() returns a frame byte, so its result is only valid until the next resolve() —
 * never hold two of these across a page-in, or a refill of frame 0 silently changes the data that
 * the first pointer is reading (the P03e fault was exactly this aliasing, not a bounds error). */
static u8 *resolve(u32 va)
{
    return &frm[pg_load(va / FRMB)][va % FRMB];
}

/* Instruction-stream reads: the paged form of rd32()/rd8(). Fetching with plain rd32() instead would
 * read mem[] directly and quietly cost nothing, so every fetch site below uses these. */
static u32 rd32_paged(u32 va)
{
    u8 *p = resolve(va);
    return p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24;
}
static u8 rd8_paged(u32 va)      { return *resolve(va); }

/* ---- stacks (SD cells each; indexes wrap, so a bug can't corrupt memory) ---- */
static u32 ds[SD], rs[SD];
static u8  sp, rsp;
static void PUSH(u32 v) { ds[sp & (SD - 1)] = v; sp++; }
#define POP()    (ds[--sp & (SD - 1)])
#define TOS      ds[(sp - 1) & (SD - 1)]
#define NOS      ds[(sp - 2) & (SD - 1)]
static void RPUSH(u32 v) { rs[rsp & (SD - 1)] = v; rsp++; }
#define RPOP()   (rs[--rsp & (SD - 1)])
#define RTOP     rs[(rsp - 1) & (SD - 1)]

/* ---- primitive table: id, dictionary name, immediate? ---- */
#define PRIMS \
 X(EXIT,"EXIT",0) X(LIT,"LIT",0) X(BRANCH,"BRANCH",0) X(ZBRANCH,"0BRANCH",0) \
 X(DO,"(DO)",0) X(LOOP,"(LOOP)",0) X(PLOOP,"(+LOOP)",0) \
 X(I,"I",0) X(J,"J",0) X(UNLOOP,"UNLOOP",0) X(EXEC,"EXECUTE",0) \
 X(DUP,"DUP",0) X(DROP,"DROP",0) X(SWAP,"SWAP",0) X(OVER,"OVER",0) X(ROT,"ROT",0) \
 X(TOR,">R",0) X(RFROM,"R>",0) \
 X(FETCH,"@",0) X(STORE,"!",0) X(CFETCH,"C@",0) X(CSTORE,"C!",0) \
 X(WFETCH,"W@",0) X(WSTORE,"W!",0) \
 X(ADD,"+",0) X(SUB,"-",0) X(MUL,"*",0) X(DIVMOD,"/MOD",0) X(UDIVMOD,"U/MOD",0) \
 X(AND,"AND",0) X(OR,"OR",0) X(XOR,"XOR",0) X(INVERT,"INVERT",0) \
 X(LSHIFT,"LSHIFT",0) X(RSHIFT,"RSHIFT",0) \
 X(ZEQ,"0=",0) X(LT,"<",0) X(ULT,"U<",0) \
 X(KEY,"KEY",0) X(KEYQ,"KEY?",0) X(EMIT,"EMIT",0) X(TYPE,"TYPE",0) \
 X(COMMA,",",0) X(WCOMMA,"W,",0) X(CCOMMA,"C,",0) \
 X(COLON,":",0) X(SEMI,";",1) X(CREATE,"CREATE",0) X(CONSTANT,"CONSTANT",0) \
 X(TICK,"'",0) X(BTICK,"[']",1) X(LITERAL,"LITERAL",1) \
 X(DOTQ,".\"",1) X(PDOTQ,"(.\")",0) X(BSLASH,"\\",1) X(PAREN,"(",1) \
 X(GPIOG,"GPIO@",0) X(GPIOS,"GPIO!",0) X(ADCG,"ADC@",0) X(MS,"MS",0) X(WAKE,"WAKE",0)

enum { P_DOCOL, P_DOVAR, P_DOCON,
#define X(id, n, f) P_##id,
PRIMS
#undef X
P_COUNT };

/* ---- input ---- */
static u8 tib[TIBSZ];
static u8 tl, ti;
static u8 errf;
static u32 savehere, savelatest;

static void err(void)
{
    u8 i, n = rd8(PAD);
    for (i = 0; i < n; i++) pl_emit(rd8(PAD + 1 + i));
    pl_emit('?'); pl_emit('\n');
    errf = 1;
}

/* parse next blank-delimited word into PAD (upper-cased); returns length */
static u8 word(void)
{
    u8 n = 0, c;
    while (ti < tl && tib[ti] <= ' ') ti++;
    while (ti < tl && tib[ti] > ' ') {
        c = tib[ti++];
        if (n < 31) { if (c >= 'a' && c <= 'z') c -= 32; wr8(PAD + 1 + n, c); n++; }
    }
    wr8(PAD, n);
    return n;
}

/* dictionary entry: [link:2][flags|len:1][name][pad to even][cf:4][body] */
/* GUARDRAIL: the link field is still 2 bytes here (P02 widens tokens only), so this find()
 * cannot walk a dictionary larger than 64 KB — the very thing 32-bit xts are for. Widen the
 * link too before R5 relies on it; see RESULT.md follow-ups. */
static u32 find(u8 n, u8 *imm)
{
    u32 h; u8 f, i;
    for (h = rd32(V_LATEST); h; h = rd16(h)) {
        f = rd8(h + 2);
        if ((f & 31) != n) continue;
        for (i = 0; i < n && rd8(h + 3 + i) == rd8(PAD + 1 + i); i++) ;
        if (i == n) { *imm = f >> 7; return (h + 3 + n + 3) & ~3u; }
    }
    return 0;
}

static u8 number(u8 n, u32 *out)
{
    u32 b = rd32(V_BASE), v = 0, d; u8 i = 0, neg = 0, c;
    if (n > 1 && rd8(PAD + 1) == '-') { neg = 1; i = 1; }
    for (; i < n; i++) {
        c = rd8(PAD + 1 + i);
        d = (c >= '0' && c <= '9') ? c - '0' : (c >= 'A' && c <= 'Z') ? c - 'A' + 10 : 99;
        if (d >= b) return 0;
        v = v * b + d;
    }
    *out = neg ? 0u - v : v;
    return 1;
}

/* GUARDRAIL: cw() is the single place that decides token width; two call sites used to write
 * the halves of a literal separately, so widening one of them silently produced a body that
 * mixed 2- and 4-byte cells and ran into the next definition. */
static void cw(u32 v) { u32 h = rd32(V_HERE); wr32(h, v); wr32(V_HERE, h + 4); }
static void clit(u32 v) { cw(rd32(V_XLIT)); cw(v); }
static void a4(void) { wr32(V_HERE, (rd32(V_HERE) + 3) & ~3u); }

/* GUARDRAIL: the code field must be found by the SAME padding rule that mkhdr_pad() used to
 * place it; the 2-byte rule (& ~1) left bodies 2-mod-4 aligned and find() then returned an
 * address two bytes off, so ' looked up one word and EXECUTE ran the wrong definition. */

/* build a header from the name currently in PAD; returns the xt */
/* GUARDRAIL: HERE must advance by the code field's own width (4 here), because P_DOCOL uses
 * w+4 as the body address; leaving it at +2 makes every call body start two bytes early.
 * GUARDRAIL: the code field is padded to 4, not 2, because P_COMMA (used for branch operands
 * in boot_min.fs) calls a4() first: an unaligned body start made `,` insert 1-3 pad bytes in
 * front of the operand, and the interpreter read the pad as the branch target — infinite loop. */
static u32 mkhdr_pad(u8 cf, u8 imm)
{
    u8 n = rd8(PAD), i; u32 h = rd32(V_HERE), x;
    wr16(h, rd32(V_LATEST)); wr8(h + 2, n | (imm << 7));
    for (i = 0; i < n; i++) wr8(h + 3 + i, rd8(PAD + 1 + i));
    x = (h + 3 + n + 3) & ~3u;
    wr32(x, cf);
    wr32(V_LATEST, h); wr32(V_HERE, x + 4);
    return x;
}
static u32 mkhdr(u8 cf)
{
    if (!word()) { err(); return 0; }
    return mkhdr_pad(cf, 0);
}

/* ---- the inner interpreter ---- */
/* GUARDRAIL: ip must be u32, not u16: a 32-bit token stream over a >64 KB dictionary wraps the
 * instruction pointer mid-definition and the interpreter keeps executing garbage instead of
 * failing — the exact defect 32-bit xts are supposed to remove. */
static void run(u32 w)
{
    u32 ip = 0;                       /* 0 = "return to C" */
    u32 a, b, n; u8 i, imm; u32 x;
    for (;;) {
        /* GUARDRAIL: the token fetch is the paging hot spot — it must go through rd32_paged(), not
         * rd32(); rd32() reads mem[] directly, so a build that "has paging" would cost 0 extra bytes
         * and the measurement would silently describe an unpaged engine. */
        u32 cf = rd32_paged(w);
        switch (cf) {
        case P_DOCOL: RPUSH(ip); ip = w + 4; break;
        case P_DOVAR: PUSH((w + 4 + 3) & ~3u); break;
        case P_DOCON: PUSH(rd32((w + 4 + 3) & ~3u)); break;
        case P_EXIT:  if (!ip) return; ip = RPOP(); break;
        /* Operands are inline in the code stream, so they cross pages with the token: read the
         * paged form too, or a literal that sits across a 256 B boundary reads mem[] unbanked. */
        case P_LIT:   PUSH(rd32_paged(ip)); ip += 4; break;
        case P_BRANCH:  ip = rd32_paged(ip); break;
        case P_ZBRANCH: if (POP()) ip += 4; else ip = rd32_paged(ip); break;
        case P_DO:    a = POP(); b = POP(); RPUSH(b); RPUSH(a); break;
        case P_LOOP: case P_PLOOP:
            n = (cf == P_LOOP) ? 1 : POP();
            a = rs[(rsp - 2) & (SD - 1)]; b = RTOP + n;          /* limit, new index */
            if ((i32)((RTOP - a) ^ (b - a)) < 0) { rsp -= 2; ip += 4; }  /* crossed limit */
            else { RTOP = b; ip = rd32_paged(ip); }
            break;
        case P_I:      PUSH(RTOP); break;
        case P_J:      PUSH(rs[(rsp - 3) & (SD - 1)]); break;
        case P_UNLOOP: rsp -= 2; break;
        case P_EXEC:   w = POP(); continue;                 /* call without fetching next */

        case P_DUP:  PUSH(TOS); break;
        case P_DROP: sp--; break;
        case P_SWAP: a = TOS; TOS = NOS; NOS = a; break;
        case P_OVER: PUSH(NOS); break;
        case P_ROT:  a = ds[(sp - 3) & (SD - 1)]; ds[(sp - 3) & (SD - 1)] = NOS; NOS = TOS; TOS = a; break;
        case P_TOR:   RPUSH(POP()); break;
        case P_RFROM: PUSH(RPOP()); break;

        case P_FETCH:  TOS = rd32(TOS); break;
        case P_STORE:  a = POP(); b = POP(); wr32(a, b); break;
        case P_CFETCH: TOS = rd8(TOS); break;
        case P_CSTORE: a = POP(); b = POP(); wr8(a, b); break;
        case P_WFETCH: TOS = rd16(TOS); break;
        case P_WSTORE: a = POP(); b = POP(); wr16(a, b); break;

        case P_ADD: b = POP(); TOS += b; break;
        case P_SUB: b = POP(); TOS -= b; break;
        case P_MUL: b = POP(); TOS *= b; break;
        case P_DIVMOD:                                     /* signed, truncating */
            b = POP(); a = TOS;
            if (b == 0) { TOS = 0; PUSH(0); }
            else if ((i32)b == -1) { TOS = 0; PUSH(0u - a); }
            else { TOS = (u32)((i32)a % (i32)b); PUSH((u32)((i32)a / (i32)b)); }
            break;
        case P_UDIVMOD:
            b = POP(); a = TOS;
            if (b == 0) { TOS = 0; PUSH(0); } else { TOS = a % b; PUSH(a / b); }
            break;
        case P_AND: b = POP(); TOS &= b; break;
        case P_OR:  b = POP(); TOS |= b; break;
        case P_XOR: b = POP(); TOS ^= b; break;
        case P_INVERT: TOS = ~TOS; break;
        case P_LSHIFT: b = POP(); TOS <<= (b & 31); break;
        case P_RSHIFT: b = POP(); TOS >>= (b & 31); break;
        case P_ZEQ: TOS = TOS ? 0 : ~0u; break;
        case P_LT:  b = POP(); TOS = ((i32)TOS < (i32)b) ? ~0u : 0; break;
        case P_ULT: b = POP(); TOS = (TOS < b) ? ~0u : 0; break;

        case P_KEY:  PUSH(pl_key()); break;
        case P_KEYQ: PUSH(pl_hw(5, 0, 0) ? ~0u : 0); break;
        case P_EMIT: pl_emit(POP()); break;
        case P_TYPE: n = POP(); a = POP(); while (n--) pl_emit(rd8(a++)); break;

        case P_COMMA:  a4(); a = rd32(V_HERE); wr32(a, POP()); wr32(V_HERE, a + 4); break;
        case P_WCOMMA: cw(POP()); break;
        case P_CCOMMA: a = rd32(V_HERE); wr8(a, POP()); wr32(V_HERE, a + 1); break;
        case P_COLON:
            savehere = rd32(V_HERE); savelatest = rd32(V_LATEST);
            if (mkhdr(P_DOCOL)) wr32(V_STATE, 1);
            break;
        case P_SEMI:   cw(rd32(V_XEXIT)); wr32(V_STATE, 0); break;
        case P_CREATE: if (mkhdr(P_DOVAR)) a4(); break;
        case P_CONSTANT:
            if (mkhdr(P_DOCON)) { a4(); a = rd32(V_HERE); wr32(a, POP()); wr32(V_HERE, a + 4); }
            break;
        case P_TICK: case P_BTICK:
            i = word(); x = i ? find(i, &imm) : (u32)0;
            if (!x) err();
            else if (cf == P_TICK) PUSH(x);
            else clit(x);
            break;
        case P_LITERAL: clit(POP()); break;
        case P_DOTQ:
            if (ti < tl) ti++;                              /* skip one space */
            i = ti; while (ti < tl && tib[ti] != '"') ti++;
            n = ti - i; if (ti < tl) ti++;
            if (rd32(V_STATE)) {
                /* GUARDRAIL: the inline string operand is padded to the token width (4), not to 2:
                 * padding it to 2 leaves the next token 2-byte-misaligned, which only shows up
                 * when the following token straddles a word boundary on the real core. */
                cw(rd32(V_XSTR)); a = rd32(V_HERE); wr8(a, n);
                for (b = 0; b < n; b++) wr8(a + 1 + b, tib[i + b]);
                wr32(V_HERE, (a + n + 4) & ~3u);
            } else for (b = 0; b < n; b++) pl_emit(tib[i + b]);
            break;
        case P_PDOTQ:
            n = rd8_paged(ip); for (b = 0; b < n; b++) pl_emit(rd8_paged(ip + 1 + b));
            ip = (ip + n + 4) & ~3u;
            break;
        case P_BSLASH: ti = tl; break;
        case P_PAREN:  while (ti < tl) if (tib[ti++] == ')') break; break;

        case P_GPIOG: TOS = pl_hw(0, TOS, 0); break;
        case P_GPIOS: a = POP(); b = POP(); pl_hw(1, a, b); break;
        case P_ADCG:  TOS = pl_hw(2, TOS, 0); break;
        case P_MS:    pl_hw(3, POP(), 0); break;
        case P_WAKE:  pl_hw(4, 0, 0); break;
        }
        if (!ip) return;
        w = rd32_paged(ip); ip += 4;
    }
}

/* ---- outer interpreter ---- */
static void interpret(void)
{
    u8 n, imm; u32 xt; u32 v;
    errf = 0;
    while (!errf && (n = word())) {
        if ((xt = find(n, &imm))) {
            if (rd32(V_STATE) && !imm) cw(xt); else run(xt);
        } else if (number(n, &v)) {
            if (rd32(V_STATE)) clit(v); else PUSH(v);
        } else err();
    }
    if (errf) {
        sp = rsp = 0;
        if (rd32(V_STATE)) { wr32(V_HERE, savehere); wr32(V_LATEST, savelatest); }
        wr32(V_STATE, 0); ti = tl;
    }
}

static void say(const char *s) { while (*s) pl_emit(*s++); }

void forth_quit(void)
{
    int c;
    for (;;) {
        tl = ti = 0;
        for (;;) {
            c = pl_key();
            if (c == '\r' || c == '\n') break;
            if (c == 8 || c == 127) { if (tl) { tl--; say("\b \b"); } }
            else if (c >= ' ' && tl < TIBSZ - 1) { tib[tl++] = c; pl_emit(c); }
        }
        pl_emit('\n');
        interpret();
        if (sp >= SD) { say("stack?\n"); sp = rsp = 0; }
        else if (!errf) say(" ok\n");
    }
}

/* ====================================================================
 * PC build: compiles boot.fs from the primitive table and runs files
 * ==================================================================== */
#ifdef HOST
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static u32 pins;
int  pl_key(void)        { int c = getchar(); if (c == EOF) exit(0); return c; }
void pl_emit(int c)      { putchar(c); }
u32  pl_hw(int op, u32 a, u32 b)
{
    switch (op) {
    case 0: return (pins >> (a & 31)) & 1;
    case 1: pins = b ? pins | 1u << (a & 31) : pins & ~(1u << (a & 31));
            printf("[gpio %u=%u]", a, b ? 1 : 0); return 0;
    case 2: return 1000 + 100 * a;            /* fake ADC reading */
    case 4: printf("[wake]"); return 0;
    }
    return 0;
}

#ifndef IMAGE
static void boot_init(void)
{
    u32 x;
    wr32(V_HERE, DICT); wr32(V_LATEST, 0); wr32(V_BASE, 10); wr32(V_STATE, 0);
#define X(id, name, imm) \
    { const char *s = name; u8 n = 0; while (s[n]) { wr8(PAD + 1 + n, s[n]); n++; } wr8(PAD, n); \
      x = mkhdr_pad(P_##id, imm); \
      if (P_##id == P_LIT) wr32(V_XLIT, x); \
      if (P_##id == P_EXIT) wr32(V_XEXIT, x); \
      if (P_##id == P_PDOTQ) wr32(V_XSTR, x); }
    PRIMS
#undef X
}
#endif

static int load(const char *file)
{
    char line[256]; int ln = 0; FILE *f = fopen(file, "r");
    if (!f) { fprintf(stderr, "cannot open %s\n", file); return 1; }
    while (fgets(line, sizeof line, f)) {
        size_t n = strlen(line); ln++;
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r')) n--;
        if (n >= TIBSZ) { fprintf(stderr, "%s:%d: line too long (%zu >= %d)\n", file, ln, n, TIBSZ); return 1; }
        memcpy(tib, line, n); tl = n; ti = 0;
        interpret();
        if (errf) { fprintf(stderr, "%s:%d: error\n", file, ln); return 1; }
        if (sp >= SD) { fprintf(stderr, "%s:%d: stack underflow\n", file, ln); return 1; }
    }
    fclose(f);
    return 0;
}

int main(int argc, char **argv)
{
    const char *dump = 0; int i, interactive = 0;
#ifndef IMAGE
    boot_init();
#endif
    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-d") && i + 1 < argc) dump = argv[++i];
        else if (!strcmp(argv[i], "-i")) interactive = 1;
        else if (load(argv[i])) return 1;
    }
    if (dump) {
        FILE *f = fopen(dump, "w"); u32 n = rd32(V_HERE), k;
        fprintf(f, "/* generated by uforth -d: %u of %u bytes used */\nstatic u8 mem[MEMSZ] = {\n", n, MEMSZ);
        for (k = 0; k < n; k++) fprintf(f, "0x%02x,%s", mem[k], (k % 16 == 15) ? "\n" : "");
        fprintf(f, "\n};\n"); fclose(f);
        fprintf(stderr, "image: %u bytes of %u (%u free)\n", n, MEMSZ, MEMSZ - n);
    }
    if (interactive) forth_quit();
    return 0;
}
#endif
