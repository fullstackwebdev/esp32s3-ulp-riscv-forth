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

/* ---- P30: the code-structure knobs, one source for five variants ----
 * GUARDRAIL: each knob is a -D switch, never an edit, because variant A has to compile to P29's exact
 * bytes — if A is changed at all the 4934 B bar it must reproduce stops being the same machine.
 * P30_NOINLINE  — resolve/pg_load/rd16_paged out of line (B and up)
 * P30_OUTOFLINE — one noinline function per primitive body (C and up), see gen_oflow.py
 * P30_HANDCOPY  — explicit word moves instead of a struct copy / zero loop (D and up) */
#if defined(P30_NOINLINE) || defined(P30_OUTOFLINE)
#define P30_NI __attribute__((noinline))
#else
#define P30_NI
#endif

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
/* P29: the layer's fourth hook. P22/P27 charged only three; the 1024 B layer (P26) needs a way to
 * stop the machine when the last task retires, and a hook that nothing calls is a stubbed hook. */
void pl_halt(int code);                  /* stop the machine; code 0 = no tasks left */

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

/* ---- P33: transparency removed, and why nothing else moved ----------------
 * P32 priced transparent paging at 2466 B and 800 B over the pool. A visible block interface
 * does not need any of the machinery that buys *transparency* — frames, a page table, a paged
 * fetch path, a fault/retry state machine — because a Forth word that asks for block 3 is not
 * touching an address it believes is resident. So the frames, the table and the two paged readers
 * go, and nothing else does: every other budget line (mem, tsk, tib, mailbox, rings, vm_live) and
 * every restored primitive (I J UNLOOP GPIO! ' CONSTANT ( ." (.")) stays exactly as P32 D left it.
 *
 * GUARDRAIL: keep the call sites spelled rd16_paged/rd32_paged and alias them to the direct
 * readers here. Rewriting the vm_enter call sites to rd16() would make the E-vs-D comparison a
 * comparison of two edited machines instead of one machine with one lever (P30's rule).
 * GUARDRAIL: the alias must stay a macro, not a wrapper function — a wrapper is a call the
 * compiler may refuse to inline at -Os, and then "paging removed" would show up as +8 B of
 * engine, i.e. the measurement would price the alias instead of the removal. */
#if defined(P33_NOPAGE)
#define rd16_paged(a) rd16(a)
#define rd32_paged(a) rd32(a)
#else
/* ---- paging: 4 x 512 B frames + a 4-entry page table (P22's lines, carried into the 16-bit engine)
 * GUARDRAIL: frames/ptab must stay uninitialised statics — an initialiser moves them to .data, so the
 * same bytes land in .bin and in .bss and the budget is charged twice (P20 variant D).
 * GUARDRAIL: FRMB and NFRM must stay powers of two, because resolve() divides/remainders by FRMB and
 * pg_load() indexes ptab by the frame number; a non-power-of-two silently reads the wrong page. */
#define NFRM 4
#define FRMB 512
static u8  frm[NFRM][FRMB];          /* 2048 B, .bss */
static u32 ptab[NFRM];               /* 16 B, .bss; entry = virtual page + 1, 0 = frame empty */

/* GUARDRAIL: P30_NI is deliberately empty for variant A — pg_load() has five call sites and at -Os the
 * inlining is part of the 4934 B baseline; attributing the variant's savings needs A byte-identical. */
static P30_NI u32 pg_load(u32 pg)
{
    u32 f, i;
    for (f = 0; f < NFRM; f++) if (ptab[f] == pg + 1) return f;
    for (i = 0; i < FRMB; i++) frm[0][i] = rd8(pg * FRMB + i);
    ptab[0] = pg + 1;
    return 0;
}

/* GUARDRAIL: resolve() returns a frame byte that is only valid until the next resolve() — holding two
 * of these across a page-in aliases them onto one frame (the P03e fault). Nothing here holds two. */
static P30_NI u8 *resolve(u32 va)
{
    return &frm[pg_load(va / FRMB)][va % FRMB];
}

/* GUARDRAIL: every instruction-stream read must use the paged forms. Reading the stream with rd16()
 * reaches mem[] directly, so a build that claims to page would cost 0 extra bytes and the measurement
 * would describe an unpaged engine. */
static P30_NI u16 rd16_paged(u32 va)
{
    u8 *p = resolve(va);
    return (u16)(p[0] | p[1] << 8);
}
static u32 rd32_paged(u32 va)
{
    u8 *p = resolve(va);
    (void)p;
    return (u32)rd16_paged(va) | (u32)rd16_paged(va + 2) << 16;
}
#endif /* !P33_NOPAGE */

/* ---- I/O buffers and the VM-state line (P22/P04 budget lines) ----
 * GUARDRAIL: keep these uninitialised statics, and keep them touched from main(): a static array whose
 * address never escapes is dead-store-eliminated together with --gc-sections, and the first P22 link
 * reported a fit that was 728 B of budget lines short because of exactly that. */
static u8  cmd_ring[128], out_ring[256];   /* 384 B, .bss (P04) */
static u32 mailbox[54];                    /* 216 B, .bss (P04 status mailbox) */
#if !defined(P33_NOPAGE)
static u8  ptab_lru_reserve[234];          /* 250 - 16 of ptab[] above, .bss (4.3 "page table + LRU") */
#endif

/* ---- P33: the visible block layer's only C ----
 *
 * A Forth word can hold a block number, compute an offset, copy bytes and decide what a failure
 * means; it cannot put a request into the mailbox, ring the doorbell and bound the wait, because
 * that is a hardware handshake with a cycle budget (P16: 144 us, 2740 cycles), not arithmetic.
 * So the C side is exactly one primitive, BLKXFER, and everything an operator sees is Forth:
 * BLOCK / UPDATE / SAVE / BLK-ABORT and the named codes in src/blocks.fs.
 *
 * The buffer is inside mem[], at the top, above the space the dictionary grows into:
 * GUARDRAIL: the buffer must live in mem[] — C@/!/TYPE address mem[] by offset, so a separate
 * `static u8 blkbuf[512]` would be 512 B no Forth word can reach, i.e. a budget line that cannot
 * be a block buffer at all. Keeping it at MEMSZ-BLKSZ leaves the dictionary its 852 usable bytes
 * and charges the 512 B to the pool, which is exactly where the frames it replaces came from.
 * GUARDRAIL: the wait is a counted loop, never `while (!status)`. An unbounded spin on the ULP
 * blocks the only core the whole machine has (there is no preemption: run() is the scheduler), so
 * BLKWAIT is the bound and running out of it is a *named* result, not a hang. */
#if defined(P33_BLOCK)
#ifndef BLKSZ
#define BLKSZ  512              /* one block = one buffer; 4 blocks = a 2 KB file */
#endif
#ifndef BLKWAIT
#define BLKWAIT 4096            /* iterations, not cycles: ~10x P16's 2740-cycle fetch */
#endif
#define BLKADR (MEMSZ - BLKSZ)  /* the buffer's Forth address: the top of mem[] */
enum { BLK_READ = 0, BLK_WRITE = 1, BLK_ABORT = 2 };
enum { BK_OK = 0, BK_BUSY = -2, BK_NOSERVER = -3, BK_CRC = -4, BK_BUFOVER = -6 };

/* ---- P38 fix 4: the buffer must sit above the dictionary high-water mark ----
 * GUARDRAIL: P33 built the host with MEMSZ=2304, so BLKADR was 1792 while a test that loads the
 * 456 B layer reaches HERE=1842: the first BLKXFER overwrote the newest definitions and the next
 * line failed to parse (`."?`). The overlap is silent — the fetch "works" — so it has to be
 * refused by name before the copy, not noticed afterwards. `blk_place_ok()` is the one predicate.
 * Checked at the two places that can see the two different questions:
 *   - boot (`blk_boot_assert`): is the *pool* shaped so a block buffer plus the layer's dictionary
 *     can both exist? That is a sizing fact and is knowable before the first definition.
 *   - entry to every transfer: in the host build the dictionary grows while files load, so the final
 *     HERE does not exist at boot — the first transfer is the first instant the answer is known, and
 *     the check must be there or the very fetch that corrupts the dictionary is the first to notice.
 * P38 also reports it to a program: BLKXFER returns BK_BUFOVER and BLOCK's RAISE names it. */
#ifndef BLKRES
#define BLKRES 512              /* smallest dictionary the layer fits in (P33 measured 456 B) */
#endif
static i32 blk_place_ok(void) { return rd32(V_HERE) <= (u32)BLKADR; }
static i32 blk_boot_ok(void)  { return BLKADR >= DICT + BLKRES; }
/* GUARDRAIL: the message must name both numbers and the boundary — "overlap" alone sends the reader
 * back to the disassembly, which is how P33 spent a run on a parse error.
 * GUARDRAIL: the printing is HOST-only. The ULP build has no libc (no printf, P29), so a message call
 * left unguarded is a link error on the chip, not a nicety — the chip's half is the returned status:
 * blk_xfer() hands BK_BUFOVER to Forth, and the boot check is `pl_halt(1)` in the ULP's main. */
#ifdef HOST
/* GUARDRAIL: <stdio.h> used to be included only in the HOST section far below, so P38's assert —
 * which lives next to blk_xfer, above it — was compiled without a printf prototype (implicit
 * declaration, -Wbuiltin-declaration-mismatch). The ULP build must not see this include at all. */
#include <stdio.h>
static void blk_boot_assert(void)
{
    if (!blk_boot_ok())
        printf("\nERR_BUFOVER(boot): block_buffer=%u < DICT+BLKRES=%u (MEMSZ=%u BLKSZ=%u) — the pool\n"
               "leaves the buffer inside the dictionary; raise MEMSZ.\n",
               (unsigned)BLKADR, (unsigned)(DICT + BLKRES), (unsigned)MEMSZ, (unsigned)BLKSZ);
}
static void blk_place_assert(const char *when)
{
    if (blk_place_ok()) return;
    printf("\nERR_BUFOVER(%s): dict_here=%u > block_buffer=%u (MEMSZ=%u, BLKSZ=%u)\n",
           when, (unsigned)rd32(V_HERE), (unsigned)BLKADR, (unsigned)MEMSZ, (unsigned)BLKSZ);
}
#else
static void blk_boot_assert(void)          { if (!blk_boot_ok()) pl_halt(1); }
static void blk_place_assert(const char *w){ (void)w; }
#endif
static u32 blk_out;             /* 1 = a request is outstanding. P16: exactly one, ever */

static u32 blk_sum(void)
{
    u32 k, s = 0;
    for (k = 0; k < BLKSZ; k++) s += rd8(BLKADR + k);
    return s & 0xffffu;
}

/* One request, one bounded wait, one status. Never returns before the buffer state is known. */
static i32 blk_xfer(u32 blk, u32 op)
{
    u32 i;
    /* GUARDRAIL: the placement check is the first statement: a fetch into an overlapping buffer
     * overwrites the dictionary *before* any status could report it (P33/P37), so the refusal has to
     * precede the doorbell and the copy. BK_BUFOVER is the status the Forth layer names. */
    if (!blk_place_ok()) { blk_place_assert("xfer"); return BK_BUFOVER; }
    /* GUARDRAIL: the poll must read the status through volatile, or GCC hoists the load out of
     * the loop and the driver only ever sees the value it wrote itself (always 0 = no server). */
    volatile u32 *st = &mailbox[2];
    if (op == BLK_ABORT) { blk_out = 0; return BK_OK; }   /* the operator says the main core is dead */
    /* GUARDRAIL: one outstanding request is a hardware constraint, not a policy — P16 measured
     * two in flight corrupting silently, with a valid CRC on both. Refuse; do not queue. */
    if (blk_out) return BK_BUSY;
    blk_out = 1;
    mailbox[0] = blk; mailbox[1] = op;
    mailbox[3] = (op == BLK_WRITE) ? blk_sum() : 0u;      /* the checksum travels in the mailbox */
    *st = 0;                                             /* 0 = pending */
    pl_hw(6, 0, 0);                                      /* doorbell: P23, 176 us */
    for (i = 0; i < BLKWAIT; i++) if (*st) break;
    /* GUARDRAIL: leave blk_out set on a timeout — a request nobody answered is still out there,
     * so the next BLOCK is refused BUSY instead of racing the answer into a stale buffer. */
    if (!*st) return BK_NOSERVER;
    if (*st != 1u) { blk_out = 0; return (i32)(0u - *st); }  /* a nack: the server's own code, negative */
    if (op == BLK_READ && mailbox[3] != blk_sum()) { blk_out = 0; return BK_CRC; }
    blk_out = 0;
    return BK_OK;
}
#endif /* P33_BLOCK */

/* ---- P27: the interpreter state is one struct, so a switch is a struct copy ----
 *
 * P26 found that dsp/rsp/ip were C locals/statics of run(), so YIELD rotated the
 * scheduler's records while the machine stayed put. Everything run() keeps live
 * across a dispatch is now in a VM. The full list, and why each item is there:
 *
 *   ds[SD], rs[SD]  the machine's two stacks (the values, not just the pointers:
 *                   P13 measured peaks of 20 data + 7 return cells, so a task
 *                   that is switched out owns up to 27 live cells)
 *   sp, rsp         the two stack pointers
 *   w               the dispatch position: the xt of the token about to execute
 *   ip              that token's continuation; ip == 0 means "return to C"
 *
 * Not saved, because they are dead across a dispatch: run()'s temporaries
 * a, b, n, i, imm, x. Each `case` stores before it loads (checked case by case),
 * so no value taken before a dispatch is read after it.
 *
 * Not saved, because they are not the machine: tib/ti/tl/errf belong to the outer
 * interpreter (the REPL that owns the keyboard), not to a task's execution.
 */
typedef struct { u32 DS[SD]; u32 RS[SD]; u8 SP, RSP; u16 W, IP; } VM;
static VM vm_live;
static VM *V = &vm_live;              /* the machine currently executing */
/* GUARDRAIL: fields are upper-case and the short names are macros, so no lower-case
 * identifier can name a VM member — `vm.w` silently became `vm.(V->w)` and did not
 * compile. Access a member through the field names (V->W), or through a VM* alias. */
#define sp  (V->SP)
#define rsp (V->RSP)
#define ds  (V->DS)
#define rs  (V->RS)
#define w   (V->W)
#define ip  (V->IP)
static void PUSH(u32 v) { ds[sp & (SD - 1)] = v; sp++; }
#define POP()    (ds[--sp & (SD - 1)])
#define TOS      ds[(sp - 1) & (SD - 1)]
#define NOS      ds[(sp - 2) & (SD - 1)]
static void RPUSH(u32 v) { rs[rsp & (SD - 1)] = v; rsp++; }
#define RPOP()   (rs[--rsp & (SD - 1)])
#define RTOP     rs[(rsp - 1) & (SD - 1)]

/* ---- primitive table: id, dictionary name, immediate? ---- */
enum { P_DOCOL, P_DOVAR, P_DOCON,
#define X(id, n, f) P_##id,
/* GUARDRAIL: p33_prims.inc is p31_prims.inc plus the block primitive behind -DP33_BLOCK, so a
 * build without P33_BLOCK gets P31's exact table and the delta attributed to the layer is the
 * layer's (the same reason P31 kept one entry per line). */
#include "p33_prims.inc"
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
/* ---- P31: instrumented name lookups (host derivation build only, -DP31_TRACE) ----
 * GUARDRAIL: the trace records the *header address*, not the name in PAD — PAD is the parser's
 * scratch buffer and is overwritten by the next word(), so a name captured there belongs to some
 * later token. The header keeps the primitive's own name for as long as the dictionary lives. */
#ifdef P31_TRACE
#include <stdio.h>
u32 p31_prim_here;                       /* V_HERE right after boot_init: below it is primitive */
static u32 p31_hits[8192]; static int p31_nhit;
static void p31_report(void)
{
    int i, j; u8 n, k;
    for (i = 0; i < p31_nhit; i++) {
        u32 h = p31_hits[i];
        if (h >= p31_prim_here) continue;             /* a layer/prelude word, not a primitive */
        for (j = 0; j < i; j++) if (p31_hits[j] == h) break;
        if (j < i) continue;                          /* reported already */
        n = rd8(h + 2) & 31;
        fprintf(stderr, "PRIM ");
        for (k = 0; k < n; k++) fputc(rd8(h + 3 + k), stderr);
        fputc('\n', stderr);
    }
}
#endif

static u16 find(u8 n, u8 *imm)
{
    u32 h; u8 f, i;
    for (h = rd32(V_LATEST); h; h = rd16(h)) {
        f = rd8(h + 2);
        if ((f & 31) != n) continue;
        for (i = 0; i < n && rd8(h + 3 + i) == rd8(PAD + 1 + i); i++) ;
        /* GUARDRAIL: a successful find is the only evidence that a primitive is *required* — the
         * layer may define a word with the same name, which is why the header range decides. */
        if (i == n) {
#ifdef P31_TRACE
            if (p31_nhit < (int)(sizeof p31_hits / sizeof p31_hits[0])) p31_hits[p31_nhit++] = h;
#endif
            *imm = f >> 7; return (h + 3 + n + 1) & ~1u; }
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

/* ---- P27: task records and the one switch mechanism ----
 *
 * A record is the VM plus two bytes of scheduler policy. `vm_switch(next)` is the
 * ONLY code that saves one machine and restores another, and both PAUSE and the
 * page-fault retry call it: that is what makes them one mechanism rather than two.
 */
#ifndef NTSK
#define NTSK 3
#endif
typedef struct { VM vm; u16 entry; u8 state; } TSK;   /* state: 0 free, 1 ready, 2 done */
static TSK tsk[NTSK];
static int cur = -1;                  /* -1 = run() is the outer interpreter, not a task */
static u32 vm_switches, vm_sw_pause, vm_sw_fault, vm_faults;
static u32 vm_sw_taskexit;            /* switches caused by a task finishing (EXIT with ip 0) */
static u32 vm_sw_first;               /* the first dispatch into a task: nothing to save */
/* Depth of the C calls into the interpreter. A switch must NOT change it: if PAUSE or a
 * fault returned through C, a task that yielded mid-word would unwind to its caller and the
 * resume would start a second vm_enter. Measured so the claim is not an assertion. */
static int vm_depth, vm_max_depth;
static u32 vm_faults_left;            /* injected faults remaining (0 = page resident) */
static void (*vm_trace)(int from, int to);   /* host hook: one call per switch */

static int vm_next_ready(int from)
{
    int k, i;
    for (i = 1; i <= NTSK; i++) {
        k = (from + i) % NTSK;
        if (tsk[k].state == 1) return k;
    }
    return -1;
}

#if defined(P30_HANDCOPY)
/* ---- P30 D: hand-written VM copy and task zeroing ----
 * GUARDRAIL: `tsk[from].vm = *V` is a 136 B struct copy, and at -Os rv32imc GCC emits a libgcc `memcpy`
 * *call* for it (232 B, P29) — the saving only exists if the copies are word moves the pattern matcher
 * cannot turn back into a library call, so they are unrolled four words per iteration and the loop
 * bound is the struct's own size, not a byte count. Measured: a plain `while (n--) *p++ = 0;` and
 * P29's double zero loop both become `tail memset`; this form does not (artifacts/zt.c). */
static void vm_copy(VM *d, const VM *s)
{
    u32 *dp = (u32 *)d, *sp32 = (u32 *)s;
    int n = (int)(sizeof(VM) / 4);
    while (n > 0) { dp[0] = sp32[0]; dp[1] = sp32[1]; dp[2] = sp32[2]; dp[3] = sp32[3];
                    dp += 4; sp32 += 4; n -= 4; }
}
#endif

/* Save the live machine into `saved`, load another one. No C stack involved: the
 * caller is inside run()'s loop and simply continues executing the new machine. */
static void vm_switch(int next)
{
    int from = cur;
    vm_switches++;
#if defined(P30_HANDCOPY)
    /* GUARDRAIL: the struct copy compiles to a libgcc memcpy *call* on rv32imc at -Os (232 B, P29), so
     * copy word by word here — and copy the stacks by element, not by memcpy, or the saving is zero. */
    if (from >= 0) vm_copy(&tsk[from].vm, V);
#else
    if (from >= 0) tsk[from].vm = *V;    /* struct copy = the whole switch point */
#endif
    cur = next;
#if defined(P30_HANDCOPY)
    if (next >= 0) vm_copy(V, &tsk[next].vm);
#else
    if (next >= 0) *V = tsk[next].vm;
#endif
    if (vm_trace) vm_trace(from, next);
}

/* A switched-in task has no C caller to return to, so ip == 0 means the task itself
 * is finished: retire it and give the CPU to the next ready task. */
static int vm_task_leave(void)
{
    int nx;
    if (cur < 0) return 0;               /* outer interpreter: a plain C return is right */
    tsk[cur].state = 2;
    nx = vm_next_ready(cur);
    /* P29: the fourth hook, called for real when the last task retires. GUARDRAIL: keep this call on
     * the retire path — a hook that nothing calls is a stub, and a stub's bytes are not the layer's. */
    if (nx < 0) { pl_halt(0); return 0; } /* last task: unwind to the C driver */
    vm_sw_taskexit++;
    vm_switch(nx);
    return 1;
}

static void vm_task_init(int k, u16 xt)
{
    int j;
#if defined(P30_HANDCOPY)
    /* GUARDRAIL: P29's two 16-iteration zero loops compile to a libgcc `memset` call (168 B); keep the
     * four-words-per-iteration form, which the loop-distribute-pattern pass does not recognise —
     * rewriting it as one loop over DS and RS restores the memset call and the 168 B with it. */
    {
        u32 *zp = (u32 *)&tsk[k].vm;
        int zn = (int)(sizeof(VM) / 4);
        while (zn > 0) { zp[0] = zp[1] = zp[2] = zp[3] = 0u; zp += 4; zn -= 4; }
    }
#else
    for (j = 0; j < SD; j++) { tsk[k].vm.DS[j] = 0; tsk[k].vm.RS[j] = 0; }
#endif
    tsk[k].vm.SP = 0; tsk[k].vm.RSP = 0;
    tsk[k].vm.W = xt; tsk[k].vm.IP = 0;  /* ip 0 = the task's outermost word ends via EXIT */
    tsk[k].entry = xt; tsk[k].state = 1;
}

static void vm_enter(void);

/* Host driver: give each ready task a turn until all are done. */
static void vm_run_tasks(void)
{
    int nx = vm_next_ready(cur);
    if (nx < 0) return;
    vm_sw_first++;
    vm_switch(nx);                       /* cur -1 -> first task; saves nothing, loads it */
    vm_enter();
    while (vm_next_ready(cur) >= 0) vm_enter();
}

/* ---- the inner interpreter ---- */
static void run(u16 xt)
{
    /* GUARDRAIL: run() used to own ip/w as C locals, so nothing outside it could save a
     * machine — P26's scheduler rotated records while the engine stood still. ip and w are
     * VM fields now; do not reintroduce a local copy, a switch taken with a stale copy
     * resumes at the wrong token. */
    w = xt; ip = 0;                      /* 0 = "return to C" */
    vm_enter();
}

/* GUARDRAIL: variant C/E only. The bodies are generated from this very switch by gen_oflow.py —
 * retyping them would make the comparison a comparison of two different machines. The four
 * control-flow primitives (EXIT, EXEC, PAUSE, FAULT) cannot be a void call and stay inline. */
#if defined(P30_OUTOFLINE)
#include "uforth_prims.inc"
#endif

#ifdef P42_COUNT
/* GUARDRAIL: bench-only, must never ship. One load/add/store per dispatch (~3 instructions against a
 * ~700-cycle dispatch, <0.5 %), and it is in BOTH compared images, so the slope between them stays fair. */
volatile u32 p42_dispatches;
#endif

static void vm_enter(void)
{
    u32 a, b, n; u8 i, imm; u16 x;
    vm_depth++; if (vm_depth > vm_max_depth) vm_max_depth = vm_depth;
    for (;;) {
#ifdef P42_COUNT
        p42_dispatches = p42_dispatches + 1u;
#endif
        u16 cf = rd16_paged(w);                /* checkpoint = (w, ip): a pure read, so it retries */
        switch (cf) {
/* GUARDRAIL: the case bodies stay one per line in the .inc, cut from the original switch — a
 * hand-edited case in this file makes the next variant's D-vs-E diff meaningless (P30/P31). */
#include "p33_cases.inc"
        }
        if (!ip) { if (!vm_task_leave()) { vm_depth--; return; } continue; }
        w = rd16_paged(ip); ip += 2;
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
 * boot_init(): lay down the primitive headers in mem[]
 * ====================================================================
 * P39 moved this out of the HOST block and into the engine, so the *chip* build can boot too.
 * GUARDRAIL: until P39 this function lived inside `#ifdef HOST`, so no ULP image could ever build a
 * dictionary — every previous chip link was a sizing exercise with an empty mem[] (`-DIMAGE` baked
 * a host-compiled dictionary instead). A ULP build that tried `boot_init()` failed to link, and one
 * that guessed its own header layout would be measuring a different dictionary than the host's.
 * One definition, both builds: the host compiles it for `-d` dumps, the ULP calls it from main().
 * GUARDRAIL: keep it under `#ifndef IMAGE` — an `-DIMAGE` build carries the dumped dictionary in
 * mem[] and calling this over it silently discards the baked prelude. */
#ifndef IMAGE
static void boot_init(void)
{
    u16 x;
    wr32(V_HERE, DICT); wr32(V_LATEST, 0); wr32(V_BASE, 10); wr32(V_STATE, 0);
    /* GUARDRAIL: the boot assert runs on the zero definition state, i.e. before any dictionary word
     * can be compiled — it is the only moment the pool's *shape* can be judged without a definition
     * having already written past the buffer. The per-transfer check covers the rest. */
#if defined(P33_BLOCK)
    blk_boot_assert();
#endif
#define X(id, name, imm) \
    { const char *s = name; u8 n = 0; while (s[n]) { wr8(PAD + 1 + n, s[n]); n++; } wr8(PAD, n); \
      x = mkhdr_pad(P_##id, imm); \
      if (P_##id == P_LIT) wr16(V_XLIT, x); \
      if (P_##id == P_EXIT) wr16(V_XEXIT, x); \
      if (P_##id == P_PDOTQ) wr16(V_XSTR, x); }
    #include "p33_prims.inc"
#undef X
}
#endif

/* ====================================================================
 * PC build: compiles boot.fs from the primitive table and runs files
 * ==================================================================== */
#ifdef HOST
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static u32 pins;

#if defined(P33_BLOCK)
/* ---- P33: the main core, faked. The client side under test is the engine's own blk_xfer() ----
 * The fake file is 16 blocks of 512 B, block n byte k = k + 7n, so "the right bytes" is checkable
 * byte by byte and a stale buffer cannot pass by accident. Two failures are deliberate and by
 * block number, so the Forth test needs no harness hooks: the file has 4 real blocks, block 7 is
 * served with a wrong checksum, and every other number is a black hole that never answers.
 * GUARDRAIL: this lives in the HOST build only — on the chip the answering side is the main core,
 * and a fake server inside the ULP image would be 16 x 512 B of pool spent to lie to itself. */
#define SRVBLK 16
static u8 srv[SRVBLK][BLKSZ];

static void srv_answer(void)
{
    u32 n = mailbox[0], op = mailbox[1], k, s = 0;
    /* GUARDRAIL: a block the file does not contain must stay *silent*, not nack — the no-answer
     * path is the one that must be measured, and a fake server that always answers cannot show it. */
    if (n != 7u && n >= 4u) return;
    if (op == BLK_READ)      for (k = 0; k < BLKSZ; k++) wr8(BLKADR + k, srv[n][k]);
    else if (op == BLK_WRITE) for (k = 0; k < BLKSZ; k++) srv[n][k] = rd8(BLKADR + k);
    for (k = 0; k < BLKSZ; k++) s += srv[n][k];
    mailbox[3] = (n == 7u) ? (s ^ 1u) & 0xffffu : s & 0xffffu;
    mailbox[2] = 1u;                     /* answered: 1 = ok */
}
#endif

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
    /* GUARDRAIL: op 6 is the block doorbell (P23's ring). Adding it to the documented op list is
     * what keeps pl_hw from being "four ops and a default return 0" — a silent 0 there would make
     * every block request look answered-but-empty, i.e. a zero-filled buffer that no test catches. */
    case 6:
#if defined(P33_BLOCK)
        srv_answer();
#endif
        return 0;
    }
    return 0;
}
/* GUARDRAIL: the host build needs pl_halt's definition or the link fails in vm_task_leave, and a
 * build that does not link cannot derive anything (P29 added the fourth hook; P26's host block
 * predates it). Host-only: the ULP harness defines the real one. */
void pl_halt(int code)   { (void)code; }

/* GUARDRAIL: boot_init() now lives in the engine section above (P39) — do not re-add a HOST-local
 * copy here, or the host's `-d` dictionary and the chip's dictionary stop being the same bytes. */
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
#if defined(P33_BLOCK)
    { u32 n0, k0;   /* the fake file's contents: block n byte k = k + 7n */
      for (n0 = 0; n0 < SRVBLK; n0++) for (k0 = 0; k0 < BLKSZ; k0++) srv[n0][k0] = (u8)(k0 + 7 * n0); }
#endif
#ifdef P31_TRACE
    /* GUARDRAIL: this must be taken between boot_init() and the first load() — after the first file
     * the ceiling moves and layer headers are misread as primitives (P31). */
    p31_prim_here = rd32(V_HERE);
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
#if defined(P33_BLOCK)
    /* GUARDRAIL: print the *server's* copy after the run — the write-back claim has to be read off
     * the answering side, or a layer that rewrote its own buffer and reported success passes. */
    printf("\nSRV blk0[0]=%02x blk0[9]=%02x blk3[9]=%02x\n", srv[0][0], srv[0][9], srv[3][9]);
#endif
#ifdef P31_TRACE
    p31_report();
#endif
    return 0;
}
#endif
