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
/* GUARDRAIL: one halfword load, not two byte loads through rd8(). Measured on the chip (P42/E-053):
 * 1 757.75 -> 1 139.25 cycles per dispatch, -35.2 %, because rd16 used to pay two rd8() calls and each
 * call on this core costs ~24 cycles per instruction with no cache to hide it.
 * Tokens and cells are only ever written through wr16/wr32 at even addresses, so `lh` is legal; if that
 * ever stops being true the core raises a misaligned-access trap instead of returning a byte-swapped
 * value, which is the failure we want. Do NOT add a byte-pair fallback: it would hide exactly that bug.
 * Out-of-range keeps the old answer (0) so wild pointers behave as before. */
#if defined(ALIGN_TRAP)
static u16 rd16(u32 a)           { if (a & 1u) pl_halt(0x50u); return *(volatile u16 *)(mem + a); }
#else
/* GUARDRAIL: the old test was `a + 1u < MEMSZ`, which WRAPS for a = 0xFFFFFFFF: the sum becomes 0, the
 * test passes, and the load reads mem - 1 — a wild pointer, not a rejected address. (`-1 @` reaches it.)
 * Compare the address, never the address plus its own width. P(a) never had this bug because it tests `a`. */
static u16 rd16(u32 a)           { return a < MEMSZ - 1u ? *(volatile u16 *)(mem + a) : 0u; }
#endif
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
/* GUARDRAIL: 4096 iterations is ~2 ms — shorter than the host's poll interval, so the FIRST request timed
 * out and then answered ERR_BUSY forever (a timed-out request deliberately keeps blk_out set, so one missed
 * poll bricks the layer until reset). Measured on the chip: `0 BLOCK .` -> ERR_NO_SERVER, then everything
 * ERR_BUSY. The host polls every FreeRTOS tick (10 ms), so the wait must be comfortably longer than that:
 * 2 000 000 iterations ~= 0.2-0.4 s, which is the value the experimental tree validated on hardware. */
#define BLKWAIT 2000000         /* iterations, not cycles: must exceed the host's 10 ms poll interval */
#endif
#define BLKADR (MEMSZ - BLKSZ)  /* the buffer's Forth address: the top of mem[] */
/* ---- published for the MAIN CORE (R5) ----
 * `mem` and `mailbox` are static, so the ULP map generator never exports them and the host cannot reach
 * the buffer or the request words by symbol. Publish their ADDRESSES at first run and let the host use a
 * pointer into RTC slow memory — remembering that these are offsets from RTC_SLOW_MEM, not absolute
 * addresses (E-073: dereferencing one directly panics with EXCVADDR = the offset).
 * GUARDRAIL: no initialisers here. `(u32)&mem[0]` is a link-time constant for the ULP but GCC rejects it
 * as a static initialiser in the host build, and the host build is the image generator — if that fails the
 * vocabulary is never baked. They are set at first run in ulp_repl.c instead. */
volatile u32 repl_mem_addr;
volatile u32 repl_blk_off;
/* GUARDRAIL: the transfer SIZE must be published, not assumed. The host server had its own `#define BLK_SZ
 * 256` while the ULP was built with BLKSZ 128: every write was checksummed over 256 B against the ULP's
 * 128, so SAVE nacked with a bogus +4, and the extra 128 B overwrote mem[] and the ULP's .bss (the
 * symptom was a second boot banner appearing mid-session). One owner: the ULP's build says how big a
 * block is, and the host asserts and uses that number. */
volatile u32 repl_blk_sz;
volatile u32 repl_blk_req;              /* 1 while a request is outstanding */
volatile u32 repl_mb_addr;
enum { BLK_READ = 0, BLK_WRITE = 1, BLK_ABORT = 2 };
enum { BK_OK = 0, BK_BUSY = -2, BK_NOSERVER = -3, BK_CRC = -4, BK_BUFOVER = -6,
       /* GUARDRAIL: two codes the transfer layer never returns but the WORD layer does — a negative block
        * number and a refused dirty-buffer switch. They live in the same enum so the error spaces cannot
        * drift apart, and -5/-7 are chosen to stay clear of the transfer codes. */
       BK_RANGE = -5, BK_DIRTY = -7 };

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
    volatile u32 *mbsum = &mailbox[3];
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
    /* GUARDRAIL: the checksum MUST be read through a volatile lvalue, for the same reason as the status
     * one line above. For a READ we write mailbox[3] = 0 ourselves, so a plain load is CSE'd to the constant
     * 0: every empty block "verified" (0 == 0) and every block with data failed ERR_CRC while the server's
     * log showed both cores holding the same bytes. Measured on the board: file=65 buf=65 sum=65 and the
     * ULP still complained. This is F-108 reappearing because this tree kept an older copy of blk_xfer. */
    if (op == BLK_READ && *mbsum != blk_sum()) { blk_out = 0; return BK_CRC; }
    blk_out = 0;
    return BK_OK;
}
#endif /* P33_BLOCK */

/* ---- P51 boot shape check: the baked image and this build must agree about MEMSZ ----
 * GUARDRAIL: image.h embeds V_LATEST, and with P51 that is an ABSOLUTE address, because the header area
 * grows down from MEMSZ. The shipping image had been baked at MEMSZ 1900 while the ULP built at 1704 —
 * harmless while headers were link-chained from the bottom, fatal now: the ULP would look for headers
 * above its own mem[] and every word would be unknown. Compare the numbers at boot and stop with a code.
 * GUARDRAIL: this lives OUTSIDE the P33_BLOCK section on purpose — it is about the image, not about blocks,
 * and putting it inside that #if made block-only symbols leak into builds without them (BLKSZ undeclared). */
static void image_boot_assert(void)
{
    u32 latest = rd32(V_LATEST), here = rd32(V_HERE);
    if (latest > MEMSZ || (latest & 3u) != 0u || here > latest) pl_halt(0x51u);
}

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
/* GUARDRAIL: `ds[sp & (SD-1)]` WRAPS when sp reaches SD, so the 17th value lands in slot 0 and silently
 * corrupts whatever is there. Measured on the shipped SD=16: `15 FIB .` answers 377 instead of 610, and a
 * three-line Fibonacci file HANGS the machine (E-077). This is not a sizing question — a wrong answer with
 * no error is the worst failure this machine can produce. The index is now checked, and the check is
 * BEFORE the store so a fault leaves the stacks intact enough to recover: `stack_ovf` is reported once at
 * the dispatch boundary (vm_enter), where output is safe, and the line is abandoned with errf set.
 * GUARDRAIL: do not make this a silent clamp or a saturating push — a program that overflows must find out. */
static u8 stack_ovf;
static void PUSH(u32 v) { if (sp < SD) { ds[sp] = v; sp++; } else stack_ovf = 1; }
#define POP()    (ds[--sp & (SD - 1)])
#define TOS      ds[(sp - 1) & (SD - 1)]
#define NOS      ds[(sp - 2) & (SD - 1)]
/* GUARDRAIL: same wrap on the return stack; a nested IF/DO that overflows corrupts the return addresses
 * and the machine resumes at an unrelated token — the 15 FIB hang above is exactly this. */
static void RPUSH(u32 v) { if (rsp < SD) { rs[rsp] = v; rsp++; } else stack_ovf = 1; }
#define RPOP()   (rs[--rsp & (SD - 1)])
#define RTOP     rs[(rsp - 1) & (SD - 1)]

/* ---- primitive table: id, dictionary name, immediate? ---- */
/* P50: the assembler needs the primitive ids as literal constants. pids.h is generated from the same
 * X-macro list, and the asserts below make a drift a COMPILE error — the alternative is an asm jump table
 * that silently dispatches the wrong case, which no test would catch until a word misbehaved. */
#include "pids.h"

enum { P_DOCOL, P_DOVAR, P_DOCON,
#define X(id, n, f) P_##id,
/* GUARDRAIL: p33_prims.inc is p31_prims.inc plus the block primitive behind -DP33_BLOCK, so a
 * build without P33_BLOCK gets P31's exact table and the delta attributed to the layer is the
 * layer's (the same reason P31 kept one entry per line). */
#include "p33_prims.inc"
#undef X
P_COUNT };

/* P50 GUARDRAIL: every id the assembler hard-codes is asserted against the real enum here, so a change to
 * the primitive list breaks the build instead of the dispatcher. Add one assert per id used in dispatch.S. */
_Static_assert(P_DUP   == ID_DUP,   "pids.h drift: DUP");
_Static_assert(P_DROP  == ID_DROP,  "pids.h drift: DROP");
_Static_assert(P_SWAP  == ID_SWAP,  "pids.h drift: SWAP");
_Static_assert(P_OVER  == ID_OVER,  "pids.h drift: OVER");
_Static_assert(P_ROT   == ID_ROT,   "pids.h drift: ROT");
_Static_assert(P_ADD   == ID_ADD,   "pids.h drift: +");
_Static_assert(P_SUB   == ID_SUB,   "pids.h drift: -");
_Static_assert(P_ZEQ   == ID_ZEQ,   "pids.h drift: 0=");
_Static_assert(P_EXIT  == ID_EXIT,  "pids.h drift: EXIT");
_Static_assert(P_DOCOL == ID_DOCOL, "pids.h drift: DOCOL");
_Static_assert(P_LIT   == ID_LIT,   "pids.h drift: LIT");
_Static_assert(SD == 16, "dispatch.S assumes SD=16 for the stack wrap check");
_Static_assert(sizeof(VM) == 136, "dispatch.S hard-codes the VM layout");

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

/* ---- P51: hash dictionary, no names, headers in their own area ----
 * GUARDRAIL: names were 283 B for 81 words (average 3.5 characters: `+`, `DUP`, `.`) and each header
 * also carried a 2 B link and a length/flags byte — 730 B of a 1 146 B dictionary. A 4-byte entry
 * holding a 20-bit DJB2 hash, an 11-bit xt and the immediate flag returns 406 B, and find() becomes a
 * fixed-stride 4-byte compare instead of a link chase with up to 31 byte compares.
 * GUARDRAIL: the previous design measured only 82 B because it kept the link and the code field. The
 * saving lives entirely in *dropping* both: headers are now a contiguous array with stride 4 and no
 * link, and the xt is stored IN the entry, so the code field lives at the xt in the code area.
 * GUARDRAIL: a 32-bit word at 2-mod-4 TRAPS on rv32 (F-78: rd32 must be 4-aligned). Every entry here is
 * 4-aligned by construction — HDRTOP is a multiple of 4 and entries are written downward in steps of 4 —
 * so the whole key is one lw. Do not add a variable-length field to this area.
 * GUARDRAIL: headers grow DOWN from HDRTOP, code grows UP from DICT. They must never meet, and the check
 * is BEFORE the body is written: a dictionary that has already overwritten a header presents as a
 * wrong-word dispatch, not as an error (the same shape as F-107).
 * GUARDRAIL: 20 bits is small enough that collisions must be CHECKED at bake time (see the -d path).
 * A collision silently dispatches the wrong word, which is the one failure this machine cannot report. */
#if defined(P33_BLOCK)
#define HDRTOP BLKADR            /* headers must stay below the block buffer */
#else
#define HDRTOP MEMSZ
#endif
_Static_assert(MEMSZ % 4 == 0, "HDRTOP must be 4-aligned: header entries are rd32'd");
_Static_assert((HDRTOP) % 4 == 0, "the header area must start 4-aligned");

/* ---- messages: ONE byte on the wire, the text lives on the HP core (msg_codes.h) ----
 * GUARDRAIL: every message the engine prints goes through msg(), never a string literal. The text cost
 * 104 B of the ULP's .rodata, the scarcest resource here, while the host has 32 MB of flash it cannot
 * spend; and a string literal per call site is a second copy of a message that the host must also know.
 * GUARDRAIL: msg() is the single emit path. Do not reintroduce a per-character string loop — the point
 * is that no message text and no text-walking code is left in the ULP image. */
#include "msg_codes.h"
static void msg(u8 code) { pl_emit((int)code); }

static u32 hash_pad(u8 n)
{
    u32 h = 5381u; u8 i;
    for (i = 0; i < n; i++) h = (h * 33u) + rd8(PAD + 1 + i);
    return h & 0xfffffu;                     /* 20 bits: the entry has 11 for xt and 1 for immediate */
}

static u16 find(u8 n, u8 *imm)
{
    u32 key, hs, h;
    if (!n) return 0;
    hs = hash_pad(n);
    /* GUARDRAIL: fixed stride, no links. Every entry is one rd32 at a 4-aligned address, so a miss costs
     * a load and a compare — this loop replaced up to 31 byte compares per header on the input path,
     * which P46 measured as the single largest cost of typing at this REPL. */
    for (h = rd32(V_LATEST); h + 4u <= (u32)HDRTOP; h += 4u) {
        key = rd32(h);
        if ((key >> 12) != hs) continue;
#ifdef P31_TRACE
        if (p31_nhit < (int)(sizeof p31_hits / sizeof p31_hits[0])) p31_hits[p31_nhit++] = h;
#endif
        *imm = (u8)(key & 1u);
        return (u16)((key >> 1) & 0x7ffu);
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
    u32 hs = hash_pad(rd8(PAD)), x = rd32(V_HERE), h = rd32(V_LATEST) - 4u;
    /* GUARDRAIL: the room check precedes BOTH writes. Once the code area has been written over the header
     * area the damage is a wrong-word dispatch at some later line, not a failure here. */
    if (x + 2u > h || (x & 0x7ffu) != x) { msg(MSG_ERR_DICT); errf = 1; return 0; }
    wr16(x, cf);                                    /* the code field lives at the xt, in the code area */
    wr32(h, (hs << 12) | ((x & 0x7ffu) << 1) | (u32)(imm & 1u));
    wr32(V_LATEST, h); wr32(V_HERE, x + 2);
    return (u16)x;
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
/* GUARDRAIL: NTSK is a CAPABILITY dial, not a saving — each slot is a full 136 B VM snapshot plus its
 * entry/state, so 3 slots cost ~430 B of .bss permanently whether or not a task is ever spawned. Measured
 * 3->1 gave -280 B bss and -78 B text (i.e. ~140 B + ~40 B per slot), and 3->2 is the middle rung of the
 * blocks ladder: it pays only in combination, never on its own. It also makes the scheduler cheaper:
 * `(from + i) % NTSK` with NTSK 3 is a divide-by-constant (multiply-high sequence on RV32IMC) and with
 * NTSK 2 it is a single `and`. The cost is real: at most TWO tasks may exist at once, and a third SPAWN
 * must fail loudly rather than silently do nothing. */
#ifndef NTSK
#define NTSK 2
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
    /* GUARDRAIL: sizeof(VM) is 136 B = 34 words, which is NOT a multiple of 4, so a four-word unrolled
     * loop overruns by two words (8 B) on the last iteration — writing straight into the *next* task
     * record. Measured: two tasks worked (`1324`), three tasks hung the machine dead, and the overrun was
     * invisible until a third record sat adjacent. Copy whole words exactly, then the tail. */
    while (n >= 4) { dp[0] = sp32[0]; dp[1] = sp32[1]; dp[2] = sp32[2]; dp[3] = sp32[3];
                     dp += 4; sp32 += 4; n -= 4; }
    while (n-- > 0) *dp++ = *sp32++;
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
    /* GUARDRAIL: pl_halt(0) here was written when tasks were the *only* driver: on the last retire
     * the machine was expected to stop. With a REPL above them, halting on the last task exit kills
     * the console too — the ULP stops and the host reads silence. Return to C instead, with cur back
     * to -1 so the outer interpreter is the machine again. */
    if (nx < 0) { cur = -1; return 0; }   /* last task: unwind to the C driver */
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

#if defined(BLKPRIM)
/* ---- R5: BLOCK / UPDATE / SAVE as C primitives ---------------------------------
 * The Forth layer measured 530 B of dictionary, 146 of it constants and CREATE'd cells that existed only
 * so Forth could say `BLKERR @`. As primitives the contract is identical — a failed BLOCK leaves its named
 * code on the stack and does NOT hand back the buffer — and the cost is three headers.
 * GUARDRAIL: the failures are NAMED, not silent. GUARDRAIL: their text lives on the host (msg_codes.h):
 * a string per message here would put back the .rodata the message-code change removed. */
static u32 blkvars[3];                  /* 0 blkn, 1 blkerr, 2 blkdirty */
#define BLK_VBLKN   0u
#define BLK_VBLKERR 1u
#define BLK_VBLKDRT 2u

static void blk_errmsg(i32 st)
{
    if (st == BK_BUSY)         msg(MSG_ERR_BUSY);
    else if (st == BK_NOSERVER) msg(MSG_ERR_NOSERVER);
    else if (st == BK_CRC)      msg(MSG_ERR_CRC);
    else if (st == BK_BUFOVER)  msg(MSG_ERR_BUFOVER);
    else if (st == BK_DIRTY)    msg(MSG_ERR_DIRTY);
    else                        msg(MSG_ERR_UNNAMED);
}

static void p_blk_block(void)               /* ( n -- addr | code ) */
{
    i32 n = (i32)POP(), st;
    if (n < 0) { blkvars[BLK_VBLKERR] = (u32)BK_RANGE; msg(MSG_ERR_RANGE); PUSH((u32)BK_RANGE); return; }
    /* GUARDRAIL: one buffer, many blocks. Fetching a DIFFERENT block while the current one is dirty used to
     * discard the edits with no error at all (measured: write block 0, fetch block 1, SAVE, read block 0 ->
     * 0). Silent data loss is the worst outcome because the program believes it wrote. Refuse by name. */
    if (blkvars[BLK_VBLKDRT] && (u32)n != blkvars[BLK_VBLKN]) {
        msg(MSG_ERR_DIRTY); PUSH((u32)BK_DIRTY); return;
    }
    blkvars[BLK_VBLKN] = (u32)n;
    repl_blk_req = 1u;                      /* tell the main core something is waiting */
    st = blk_xfer((u32)n, BLK_READ);
    repl_blk_req = 0u;
    blkvars[BLK_VBLKERR] = (u32)st;
    if (st == BK_OK) { blkvars[BLK_VBLKDRT] = 0u; PUSH(BLKADR); return; }
    blk_errmsg(st); PUSH((u32)st);
}
static void p_blk_update(void) { blkvars[BLK_VBLKDRT] = 0xffffffffu; }
static void p_blk_save(void)                /* ( -- st ) */
{
    i32 st;
    if (blkvars[BLK_VBLKDRT] == 0u) { PUSH(0u); return; }
    repl_blk_req = 1u;
    st = blk_xfer(blkvars[BLK_VBLKN], BLK_WRITE);
    repl_blk_req = 0u;
    blkvars[BLK_VBLKERR] = (u32)st;
    if (st == BK_OK) blkvars[BLK_VBLKDRT] = 0u;
    PUSH((u32)st);
}
#endif

static void vm_enter(void);

/* Host driver: give each ready task a turn until all are done. */
/* Spawn by name: parse the next word out of tib, resolve it, take the first free slot.
 * GUARDRAIL: named failures only — an unknown name or a full task table must report through err(),
 * never silently do nothing, or a script that spawns three tasks appears to work with one. */
static int vm_spawn_name(void)
{
    int k;
    u8 n, im; u16 xt;
    n = word();
    if (!n) { err(); return -1; }
    xt = find(n, &im);
    if (!xt) { err(); return -1; }
    for (k = 0; k < NTSK; k++) if (tsk[k].state != 1) break;
    /* GUARDRAIL: err() prints the word in PAD, which here is the NAME BEING SPAWNED — so a full table
     * reported `TC?` and looked exactly like an unknown word (the same confusion that made the block
     * id-drift present as a bare `?`). A full table is its own failure and must say so. */
    if (k >= NTSK) { msg(MSG_ERR_TASKS); errf = 1; return -1; }
    vm_task_init(k, xt);
    return k;
}

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
        /* P50 GUARDRAIL: this `default` exists because P50 will move some primitive bodies into assembly
         * and gate their C cases out. Without it, a token whose case was removed falls through the switch
         * and the machine silently continues with unchanged stacks — the worst class of bug here, because
         * every symptom looks like a Forth error rather than a missing dispatcher entry. err() names the
         * word and sets errf, so the hole announces itself. */
        default: err(); break;
        }
        /* GUARDRAIL: the fault is reported HERE, not inside PUSH, because emitting from an arbitrary
         * primitive can recurse into output while the machine's stacks are unusable. One branch per
         * dispatch buys a named error instead of silent corruption, and the stacks are reset so the REPL
         * survives: the operator loses the line, not the session. */
        if (stack_ovf) {
            stack_ovf = 0; sp = 0; rsp = 0; msg(MSG_ERR_STACK); errf = 1;
            vm_depth--; return;
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
        /* GUARDRAIL: try number() FIRST for a numeric token. The old order was find() then number(),
         * so every literal in the source paid a *failed* full scan of the header chain (81 entries)
         * before being recognised as a number — measured at ~28 000 cycles per literal, versus ~1 139
         * for a dispatch. A Forth line is mostly numbers; this is the difference between a REPL that
         * responds and one that crawls. The fallback keeps the old order for everything else, so a word
         * named like a number (`-`) or a number that overflows still resolves exactly as before. */
        u8 c0 = mem[PAD + 1];
        int numeric = (c0 >= '0' && c0 <= '9') || (c0 == '-' && n > 1);
        if (numeric && number(n, &v)) {
            if (rd32(V_STATE)) clit(v); else PUSH(v);
        } else if ((xt = find(n, &imm))) {
            if (rd32(V_STATE) && !imm) cw(xt); else run(xt);
        } else if (!numeric && number(n, &v)) {
            if (rd32(V_STATE)) clit(v); else PUSH(v);
        } else err();
    }
    if (errf) {
        sp = rsp = 0;
        if (rd32(V_STATE)) { wr32(V_HERE, savehere); wr32(V_LATEST, savelatest); }
        wr32(V_STATE, 0); ti = tl;
    }
}

/* GUARDRAIL: no string emitter here any more. say() existed only to print the three engine errors that
 * are now one byte each (msg()), and a general string emitter on the ULP is exactly the 104 B of .rodata
 * this change removed. blk_say() in the block layer is separate and lives with its own strings. */

void forth_quit(void)
{
    int c;
    for (;;) {
        tl = ti = 0;
        for (;;) {
            c = pl_key();
            if (c == '\r' || c == '\n') break;
            if (c == 8 || c == 127) { if (tl) { tl--; msg(MSG_ERASE); } }
            else if (c >= ' ' && tl < TIBSZ - 1) { tib[tl++] = c; pl_emit(c); }
        }
        pl_emit('\n');
        interpret();
        if (sp >= SD) { msg(MSG_UNDERFLOW); sp = rsp = 0; }
        else if (!errf) msg(MSG_OK);
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
    wr32(V_HERE, DICT); wr32(V_LATEST, HDRTOP); wr32(V_BASE, 10); wr32(V_STATE, 0);
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
        /* GUARDRAIL: headers live ABOVE V_HERE now, so dumping only V_HERE bytes would bake an image with no
         * dictionary at all — every word would be unknown on the chip while the host test passed. Dump the
         * whole used span (up to HDRTOP); the extra bytes cost flash in .data, not pool. */
        FILE *f = fopen(dump, "w"); u32 n = (u32)HDRTOP, k;
        fprintf(f, "/* generated by uforth -d: %u of %u bytes used */\nstatic u8 mem[MEMSZ] = {\n", n, MEMSZ);
        for (k = 0; k < n; k++) fprintf(f, "0x%02x,%s", mem[k], (k % 16 == 15) ? "\n" : "");
        fprintf(f, "\n};\n"); fclose(f);
        /* GUARDRAIL: with P51 the honest figures are three numbers, not two: the code area (0..V_HERE),
         * the header area (V_LATEST..HDRTOP), and the free gap between them. Reporting "n of MEMSZ" would
         * now always print 100 % because the dump writes the whole span required to carry the headers. */
        {
            u32 here = rd32(V_HERE), latest = rd32(V_LATEST);
            fprintf(stderr, "image: code %u + headers %u, free %u (MEMSZ %u, %u words)\n",
                    here, (u32)HDRTOP - latest, latest - here, MEMSZ, ((u32)HDRTOP - latest) / 4u);
        }
        /* GUARDRAIL: a 20-bit hash over this dictionary must be checked when it is BUILT. A collision does
         * not fail a lookup loudly — it returns the wrong word, and the machine has no way to report that.
         * 81 words in 1 048 576 values is ~0.3 % per pair, which is exactly the odds that are never worth
         * betting when the prize is a silent wrong dispatch (F-107 showed how expensive that looks). */
        {
            u32 a, b, ka, kb;
            for (a = rd32(V_LATEST); a + 4u < (u32)HDRTOP; a += 4u) {
                ka = rd32(a) >> 12;
                for (b = a + 4u; b + 4u <= (u32)HDRTOP; b += 4u) {
                    kb = rd32(b) >> 12;
                    if (ka == kb) {
                        fprintf(stderr, "FATAL: hash collision 0x%05x between xt=%u and xt=%u — "
                                "widen the hash or rename a word\n",
                                (unsigned)ka, (unsigned)((rd32(a) >> 1) & 0x7ffu),
                                (unsigned)((rd32(b) >> 1) & 0x7ffu));
                        exit(3);
                    }
                }
            }
        }
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
