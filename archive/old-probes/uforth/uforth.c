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
enum { V_STATE = 0, V_HERE = 4, V_LATEST = 8, V_BASE = 12,
       V_XLIT = 16, V_XEXIT = 18, V_XSTR = 20,   /* xts the C code compiles */
       PAD = 24,                                  /* counted string, 32 bytes */
       DICT = 56 };

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
static void wr16(u32 a, u16 v)   { wr8(a, v); wr8(a + 1, v >> 8); }
static u32 rd32(u32 a)           { return rd16(a) | (u32)rd16(a + 2) << 16; }
static void wr32(u32 a, u32 v)   { wr16(a, v); wr16(a + 2, v >> 16); }

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

/* dictionary entry: [link:2][flags|len:1][name][pad to even][cf:2][body] */
static u16 find(u8 n, u8 *imm)
{
    u32 h; u8 f, i;
    for (h = rd32(V_LATEST); h; h = rd16(h)) {
        f = rd8(h + 2);
        if ((f & 31) != n) continue;
        for (i = 0; i < n && rd8(h + 3 + i) == rd8(PAD + 1 + i); i++) ;
        if (i == n) { *imm = f >> 7; return (h + 3 + n + 1) & ~1u; }
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

static void cw(u16 v) { u32 h = rd32(V_HERE); wr16(h, v); wr32(V_HERE, h + 2); }
static void clit(u32 v) { cw(rd16(V_XLIT)); cw(v); cw(v >> 16); }
static void a4(void) { wr32(V_HERE, (rd32(V_HERE) + 3) & ~3u); }

/* build a header from the name currently in PAD; returns the xt */
static u16 mkhdr_pad(u8 cf, u8 imm)
{
    u8 n = rd8(PAD), i; u32 h = rd32(V_HERE), x;
    wr16(h, rd32(V_LATEST)); wr8(h + 2, n | (imm << 7));
    for (i = 0; i < n; i++) wr8(h + 3 + i, rd8(PAD + 1 + i));
    x = (h + 3 + n + 1) & ~1u;
    wr16(x, cf);
    wr32(V_LATEST, h); wr32(V_HERE, x + 2);
    return x;
}
static u16 mkhdr(u8 cf)
{
    if (!word()) { err(); return 0; }
    return mkhdr_pad(cf, 0);
}

/* ---- the inner interpreter ---- */
static void run(u16 w)
{
    u16 ip = 0;                       /* 0 = "return to C" */
    u32 a, b, n; u8 i, imm; u16 x;
    for (;;) {
        u16 cf = rd16(w);
        switch (cf) {
        case P_DOCOL: RPUSH(ip); ip = w + 2; break;
        case P_DOVAR: PUSH((w + 2 + 3) & ~3u); break;
        case P_DOCON: PUSH(rd32((w + 2 + 3) & ~3u)); break;
        case P_EXIT:  if (!ip) return; ip = RPOP(); break;
        case P_LIT:   PUSH(rd16(ip) | (u32)rd16(ip + 2) << 16); ip += 4; break;
        case P_BRANCH:  ip = rd16(ip); break;
        case P_ZBRANCH: if (POP()) ip += 2; else ip = rd16(ip); break;
        case P_DO:    a = POP(); b = POP(); RPUSH(b); RPUSH(a); break;
        case P_LOOP: case P_PLOOP:
            n = (cf == P_LOOP) ? 1 : POP();
            a = rs[(rsp - 2) & (SD - 1)]; b = RTOP + n;          /* limit, new index */
            if ((i32)((RTOP - a) ^ (b - a)) < 0) { rsp -= 2; ip += 2; }  /* crossed limit */
            else { RTOP = b; ip = rd16(ip); }
            break;
        case P_I:      PUSH(RTOP); break;
        case P_J:      PUSH(rs[(rsp - 3) & (SD - 1)]); break;
        case P_UNLOOP: rsp -= 2; break;
        case P_EXEC:   w = (u16)POP(); continue;           /* call without fetching next */

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
        case P_SEMI:   cw(rd16(V_XEXIT)); wr32(V_STATE, 0); break;
        case P_CREATE: if (mkhdr(P_DOVAR)) a4(); break;
        case P_CONSTANT:
            if (mkhdr(P_DOCON)) { a4(); a = rd32(V_HERE); wr32(a, POP()); wr32(V_HERE, a + 4); }
            break;
        case P_TICK: case P_BTICK:
            i = word(); x = i ? find(i, &imm) : 0;
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
                cw(rd16(V_XSTR)); a = rd32(V_HERE); wr8(a, n);
                for (b = 0; b < n; b++) wr8(a + 1 + b, tib[i + b]);
                wr32(V_HERE, (a + n + 2) & ~1u);
            } else for (b = 0; b < n; b++) pl_emit(tib[i + b]);
            break;
        case P_PDOTQ:
            n = rd8(ip); for (b = 0; b < n; b++) pl_emit(rd8(ip + 1 + b));
            ip = (u16)((ip + n + 2) & ~1u);
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
        w = rd16(ip); ip += 2;
    }
}

/* ---- outer interpreter ---- */
static void interpret(void)
{
    u8 n, imm; u16 xt; u32 v;
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
    u16 x;
    wr32(V_HERE, DICT); wr32(V_LATEST, 0); wr32(V_BASE, 10); wr32(V_STATE, 0);
#define X(id, name, imm) \
    { const char *s = name; u8 n = 0; while (s[n]) { wr8(PAD + 1 + n, s[n]); n++; } wr8(PAD, n); \
      x = mkhdr_pad(P_##id, imm); \
      if (P_##id == P_LIT) wr16(V_XLIT, x); \
      if (P_##id == P_EXIT) wr16(V_XEXIT, x); \
      if (P_##id == P_PDOTQ) wr16(V_XSTR, x); }
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
