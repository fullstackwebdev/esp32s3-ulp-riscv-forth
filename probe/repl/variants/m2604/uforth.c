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
int  pl_key(void);      /* one character from the raw ring, or -1 when nothing is waiting */
int  pl_keyq(void);     /* 1 when a keystroke is waiting, 0 when not (KEY? used to read a dead register) */
void pl_emit(int c);                     /* write one character (may drop)  */
u32  pl_hw(int op, u32 a, u32 b);        /* 0 gpio_get 1 gpio_set 2 adc 3 ms 4 wake 5 key? */
/* P29: the layer's fourth hook. P22/P27 charged only three; the 1024 B layer (P26) needs a way to
 * stop the machine when the last task retires, and a hook that nothing calls is a stubbed hook. */
void pl_halt(int code);                  /* stop the machine; code 0 = no tasks left */

/* ---- memory map: system variables live inside mem[] ---- */
/* GUARDRAIL: the system area is packed, because every byte here pushes the code area up and costs app
 * space 1:1. V_XEXIT and V_XSTR are gone: both were assigned once by host-only boot code and read by
 * nothing (the compiler that emits EXIT/.\" uses cw() with the token directly). Removing them lets PAD
 * start at 20 instead of 24, and DICT at 52 instead of 56, which is 4 B back into the code area. */
/* GUARDRAIL: V_XEXIT and V_XSTR are NOT free even though uforth.c only *assigns* them — the EXIT and
 * PDOTQ case bodies in p31_cases.inc read them to emit their own tokens, and grepping one file was how
 * this was nearly deleted. */
/* GUARDRAIL: the three xt slots (V_XLIT/V_XEXIT/V_XSTR) are GONE with XT_PRIM: they were boot-assigned
 * copies of values the compiler can compute. That releases 6 B, so PAD starts at 16 and DICT at 48 — every
 * byte here is a byte of application space, 1:1.
 * GUARDRAIL: the earlier warning "V_XEXIT and V_XSTR are NOT free, the EXIT and PDOTQ case bodies read
 * them" is still the reason to check BOTH files before deleting state — those readers now call XT_PRIM. */
/* GUARDRAIL: the BASE slot is gone (see number()): written once, read once, and nothing can change it, so
 * the 4 B goes back to the code area - PAD starts at 12 and DICT at 44. */
/* GUARDRAIL: V_SEAL is the overlay seal (0 = no overlays in use). It costs 4 B of app space - PAD moves
 * 12 -> 16 and DICT 44 -> 48 - and it is what makes a NAME COLLISION loud instead of silent: headers grow
 * down from HDRTOP, so everything from V_SEAL upward is the RESIDENT dictionary and everything below it is
 * the current overlay. Without it, an overlay word whose 12-bit hash matches a resident word simply shadows
 * it for as long as the overlay is loaded (find() returns the first match walking down from V_LATEST), which
 * is the one failure this machine cannot report at run time. */
enum { V_STATE = 0, V_HERE = 4, V_LATEST = 8, V_SEAL = 12, V_LOADB = 16,
       PAD = 20,                                  /* counted string, 32 bytes */
       DICT = 52 };
/* GUARDRAIL: V_LOADB is the pending-block cursor for the SOURCE SWITCH below: 0 = none, otherwise
 * (block+1) in the low byte and the byte offset into that block in the high byte. It costs 4 B of app space
 * and it is what replaced LOAD's recursive interpret() call - see the note on word(). */

#ifdef IMAGE
#include "image.h"
#else
static u8 mem[MEMSZ];
#endif
static u8 junk;

static u8 *P(u32 a) { return a < MEMSZ ? mem + a : &junk; }  /* wild pointers are harmless */
static u8  rd8(u32 a)            { return *P(a); }
/* GUARDRAIL: noinline is a BUDGET pin, not a performance choice. With 3-byte headers `find()` and `mkhdr`
 * touch wr8/wr16 far more often, and GCC's decision to outline them is worth -90 B of .text — which is the
 * whole reason the header change fits: un-inlined it costs +82 B instead of -8 B, and the image would be
 * 82 B over the pool. Measured with the pin: .text 4 926 B, unchanged. Without it the number is one
 * heuristic away from 5 008 B, discovered at the worst possible time (a later edit, not this one). */
static void __attribute__((noinline)) wr8(u32 a, u8 v)     { *P(a) = v; }
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
static void __attribute__((noinline)) wr16(u32 a, u16 v)   { wr8(a, v); wr8(a + 1, v >> 8); }
static u32 rd32(u32 a)           { return rd16(a) | (u32)rd16(a + 2) << 16; }
static void wr32(u32 a, u32 v)   { wr16(a, v); wr16(a + 2, v >> 16); }
/* GUARDRAIL: host-only. A 3-byte header entry (P54) cannot be read with rd32 at all — half of the
 * entries sit at odd addresses and an `lw` there traps on rv32 — so the bake-time collision check needs
 * this reader. find() must NOT call it: there the bytes are compared one at a time on purpose, so the
 * load is the filter. Guarded out of the ULP image, where nothing reads a whole entry. */
#ifdef HOST
static u32 rd24(u32 a)           { return rd8(a) | (u32)rd8(a + 1) << 8 | (u32)rd8(a + 2) << 16; }
#endif

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
/* GUARDRAIL: sized from the PROTOCOL (BLK_MB = blk, op, status, checksum), not from P04's legacy status
 * array. It was `mailbox[54]`: 216 B of .bss for 4 indexed words (mb_get/mb_set), i.e. 200 B that bought
 * nothing — the single largest feature-neutral source of application space in the whole image. Keeping the
 * size derived from BLK_MB means the array cannot drift from the protocol that indexes it. */
#ifndef BLK_MB
#define BLK_MB 4                 /* the host bake has no ulp_repl.c; keep both ends on one number */
#endif
static u32 mailbox[BLK_MB];
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
/* GUARDRAIL (OPEN, needs a decision - see docs/20-strategy.md): a raw `n op BLKXFER` does NOT raise repl_blk_req;
 * only the Forth verbs (BLOCK/SAVE/PHASE) bracket their transfer with it. So mailbox op 3 (image load) reaches the
 * mailbox but the host task never looks, and the ULP reports BK_NOSERVER (-3) after BLKWAIT. Raising the flag inside
 * blk_xfer works and was measured at +16 B of pool (7845 -> 7861, i.e. 5 B over the 7856 budget), which is over the
 * 10 B gate for this step - so it was reverted rather than paid silently. Options: pay 16 B (application space
 * 695 -> 679), publish blk_out (volatile, host polls it: near-zero bytes but a protocol change), or wrap op 3 in a
 * Forth verb (same 10-16 B class). */
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
/* GUARDRAIL: every mailbox access goes through these two, because the volatile moved from "remember it at
 * each use" to "it lives here". The bug this prevents is real and target-specific: `mailbox[3] != blk_sum()`
 * was folded to the constant 0 we had just written, so empty blocks verified and blocks with data failed
 * ERR_CRC — on rv32 at -Os only. The host build does NOT reproduce it (measured: a mutant with the plain
 * load still passes tests/blocks.fs), which means no host test can guard this. An accessor is the only
 * defence that does not depend on remembering, on the compiler, or on the target. */
static u32  mb_get(u32 i) { volatile u32 *p = &mailbox[i]; return *p; }
static void mb_set(u32 i, u32 v) { volatile u32 *p = &mailbox[i]; *p = v; }

/* GUARDRAIL: published (volatile, global) so the MAIN CORE can see it. `repl_blk_req` is raised only by the Forth
 * VERBS, so a raw `n op BLKXFER` never told the host to look - measured as op 3 answering -3 (BK_NOSERVER). blk_out
 * already means exactly "a request is outstanding" and is set/cleared on every path, so the host polls THIS instead of
 * paying 16 B to raise repl_blk_req inside blk_xfer - the gate for that alternative was <= 4 B. */
volatile u32 repl_blk_out;      /* 1 = a request is outstanding. P16: exactly one, ever */

static u32 blk_sum(void)
{
    u32 k, s = 0;
    for (k = 0; k < BLKSZ; k++) s += rd8(BLKADR + k);
    return s & 0xffffu;
}

/* One request, one bounded wait, one status. Never returns before the buffer state is known. */
static i32 blk_xfer(u32 blk, u32 op)
{
    u32 i, st;
    /* GUARDRAIL: the placement check is the first statement: a fetch into an overlapping buffer
     * overwrites the dictionary *before* any status could report it (P33/P37), so the refusal has to
     * precede the doorbell and the copy. BK_BUFOVER is the status the Forth layer names. */
    if (!blk_place_ok()) { blk_place_assert("xfer"); return BK_BUFOVER; }
    /* GUARDRAIL: the poll must read the status through volatile, or GCC hoists the load out of
     * the loop and the driver only ever sees the value it wrote itself (always 0 = no server). */
    /* the status and the checksum are the two words this core only READS, and both are written by
     * the other core — mb_get is what keeps that honest. */
    if (op == BLK_ABORT) { repl_blk_out = 0; return BK_OK; }   /* the operator says the main core is dead */
    /* GUARDRAIL: one outstanding request is a hardware constraint, not a policy — P16 measured
     * two in flight corrupting silently, with a valid CRC on both. Refuse; do not queue. */
    if (repl_blk_out) return BK_BUSY;
    repl_blk_out = 1;
    mb_set(0u, blk); mb_set(1u, op);
    mb_set(3u, (op == BLK_WRITE) ? blk_sum() : 0u);        /* the checksum travels in the mailbox */
    mb_set(2u, 0u);                                      /* 0 = pending */
    pl_hw(6, 0, 0);                                      /* doorbell: P23, 176 us */
    /* GUARDRAIL: read the status ONCE. It used to be read up to four times after the poll (`!mb_get`,
     * `mb_get != 1`, then again for the nack value), and the main core can rewrite that word between any
     * two reads — so the loop could exit on 1 and the next read could see a nack, or a nack value could
     * be reported from a different request. One load, one decision. */
    st = 0u;
    for (i = 0; i < BLKWAIT; i++) if ((st = mb_get(2u)) != 0u) break;
    /* GUARDRAIL: leave blk_out set on a timeout — a request nobody answered is still out there,
     * so the next BLOCK is refused BUSY instead of racing the answer into a stale buffer. */
    if (st == 0u) return BK_NOSERVER;
    if (st != 1u) { repl_blk_out = 0; return (i32)(0u - st); }  /* a nack, negative */
    /* GUARDRAIL: the checksum MUST be read through a volatile lvalue, for the same reason as the status
     * one line above. For a READ we write mailbox[3] = 0 ourselves, so a plain load is CSE'd to the constant
     * 0: every empty block "verified" (0 == 0) and every block with data failed ERR_CRC while the server's
     * log showed both cores holding the same bytes. Measured on the board: file=65 buf=65 sum=65 and the
     * ULP still complained. This is F-108 reappearing because this tree kept an older copy of blk_xfer. */
    if (op == BLK_READ && mb_get(3u) != blk_sum()) { repl_blk_out = 0; return BK_CRC; }
    repl_blk_out = 0;
    return BK_OK;
}
#endif /* P33_BLOCK */

/* ---- P51: hash dictionary, no names, headers in their own area ----
 * GUARDRAIL: names were 283 B for 81 words (average 3.5 characters: `+`, `DUP`, `.`) and each header
 * also carried a 2 B link and a length/flags byte — 730 B of a 1 146 B dictionary. A 4-byte entry
 * holding a 20-bit DJB2 hash, an 11-bit xt and the immediate flag returns 406 B, and find() becomes a
 * fixed-stride 4-byte compare instead of a link chase with up to 31 byte compares.
 * GUARDRAIL: the previous design measured only 82 B because it kept the link and the code field. The
 * saving lives entirely in *dropping* both: headers are now a contiguous array with no link, and the
 * xt is stored IN the entry, so the code field lives at the xt in the code area.
 * GUARDRAIL: headers grow DOWN from HDRTOP, code grows UP from DICT. They must never meet, and the check
 * is BEFORE the body is written: a dictionary that has already overwritten a header presents as a
 * wrong-word dispatch, not as an error (the same shape as F-107).
 * GUARDRAIL: the key is small enough that collisions must be CHECKED at bake time (see the -d path).
 * A collision silently dispatches the wrong word, which is the one failure this machine cannot report.
 *
 * ---- P54: 3-byte entries, 24 bits = `imm1 | xt10 | hash13` (little-endian: imm is bit 0) ----
 * GUARDRAIL: the 4-byte entry was `imm1 | xt11 | hash20`, i.e. 8 spare bits per word (680 B of headers
 * for fields that need 24). The stride is 3 now, so an entry is NOT 2- or 4-aligned and the whole key
 * cannot be one lw any more: HDRTOP - 3k alternates parity with k, and a misaligned `lh`/`lw` TRAPS on
 * rv32 (F-78). Every access to this area is a byte access — do not "optimise" find() back to rd16/rd32.
 * GUARDRAIL: imm stays at BIT 0 because the prelude's IMMEDIATE (`LATEST DUP C@ 1 OR SWAP C!`) is the
 * only writer of that flag and it can only reach one byte. Any field order that buries imm inside a
 * byte makes IMMEDIATE a two-byte read-modify-write over its neighbour's entry.
 * GUARDRAIL: the previous `_Static_assert(MEMSZ % 4)` and `_Static_assert(HDRTOP % 4)` existed ONLY for
 * the 4-byte entries' alignment, and they are gone with them. What replaces them is the invariant the
 * new layout actually needs: xt is stored as xt/2 in 10 bits, so the code area must fit under 2 KiB.
 * GUARDRAIL: xt/2 assumes every code offset is EVEN. Tokens are u16 and a4() rounds up to 4, so the only
 * writes to V_HERE that exist keep it even — mkhdr_pad asserts that rather than trusting it (an odd xt
 * would be halved into a wrong-word dispatch, silently).
 * GUARDRAIL: 13 bits over 85 words has an expected 0.44 collisions, so the hash is not "probably fine":
 * tools/hashsearch.py proves injectivity for the baked vocabulary and the bake-time check below keeps it
 * true afterwards. The shipping multiplier is collision-free at 13 bits AND at 12 (it first collides at
 * 11: SAVE vs THEN, 0x2d4), so 13 is headroom, not luck — each word added later has a 85/8192 = 1.0 %
 * chance of colliding against the ones already there, and the bake refuses rather than mis-dispatching. */
#if defined(P33_BLOCK)
#define HDRTOP BLKADR            /* headers must stay below the block buffer */
#else
#define HDRTOP MEMSZ
#endif
#define HDRSZ 3u                 /* bytes per entry: 24 bits = imm1 | xt11 | hash12 */
/* GUARDRAIL: a primitive has NO code field in mem[], so its token cannot be an address: it is encoded at
 * the TOP of the 11-bit xt field, descending from PRIM_TAG, with the imm bit in bit 0 exactly as an address
 * token has it. find() already returns `field & ~1`, so an address token and a primitive token arrive at the
 * dispatcher looking the same — the range is what tells them apart.
 * GUARDRAIL: that costs the old 4094 ceiling. A real address must stay BELOW the tag space, so MEMSZ is now
 * capped at PRIM_ADDR_MAX and the _Static_assert below says so — the previous assert allowed an address whose
 * token would decode as a primitive id, i.e. a silently wrong-word dispatch at the top of the code area. */
#define PRIM_TAG   4094u         /* token of primitive id 0; id n is PRIM_TAG - 2n (+imm) */
/* GUARDRAIL: a primitive's token is now ARITHMETIC, not stored state. V_XLIT/V_XEXIT/V_XSTR used to hold
 * three boot-assigned copies of it (6 B of the system area plus a store each, and PAD could not start
 * before them). Any id is a compile-time constant, so the token is one too — compute it. */
#define XT_PRIM(id) ((u16)(PRIM_TAG - 2u * (u32)(id)))
/* GUARDRAIL: 10 bits of xt/2 is 2 KiB of code area, and the host suite already builds at MEMSZ 2048 —
 * at 2048 the last even offset is 2046 and xt/2 == 1023 still fits. Anything above this assert must
 * either widen the xt field (a 4th byte, i.e. no saving) or move to a token-indexed xt. */
/* GUARDRAIL: the assert that matters lives where P_COUNT exists (below the dispatch table); the tag itself
 * must not depend on the vocabulary size, because mkhdr_prim runs while that vocabulary is being built. */
/* Prove, rather than assume, that find()'s direct `mem[h]` reads are in range: the loop keeps h below
 * HDRTOP and this says the header area is inside mem[]. */
_Static_assert((HDRTOP) <= MEMSZ, "the header area lives inside mem[]: find() indexes it without rd8()");

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
    /* GUARDRAIL: the old test was `(latest & 3u) != 0u`, which only meant anything while an entry was a
     * 4-aligned word. With a 3-byte stride V_LATEST is deliberately NOT 4-aligned (it is HDRTOP - 3*N),
     * so that test would halt every correct image. What the stride needs instead is that the baked span
     * is a whole number of entries — a 4-byte image against a 3-byte engine leaves HDRTOP - latest = 1
     * mod 3, and so does any hand-baked image, which is the E-079 failure class arriving one width later.
     * GUARDRAIL: `latest > MEMSZ` stays and does NOT become `latest + 3*N`: the image carries an absolute
     * V_LATEST, so an image baked at another MEMSZ is the failure this catches (E-079). */
    if (latest > MEMSZ || ((u32)HDRTOP - latest) % HDRSZ != 0u || here > latest) pl_halt(0x51u);
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
/* GUARDRAIL: the config-dependent ids can only be asserted in the ONE configuration pids.h was derived from
 * (blocks + tasks enabled, as in the shipping chip build). They are NOT stable across configurations: a plain
 * host build has no block primitives, so every id after BLKXFER shifts, and asserting the shipping numbers
 * there fails a build that is perfectly correct - measured, the first version of this block broke
 * tests/run.sh's host_suite over SPAWN and LIT2. The rule from pids.h's own header still stands: when you add
 * or remove a primitive, re-derive the file from the enum, for the configuration you are shipping. */
#if defined(P33_BLOCK) && defined(BLKPRIM) && defined(P43_TASKS)
_Static_assert(P_BLKXFER == ID_BLKXFER, "pids.h drift: BLKXFER");
_Static_assert(P_BLOCK   == ID_BLOCK,   "pids.h drift: BLOCK");
_Static_assert(P_UPDATE  == ID_UPDATE,  "pids.h drift: UPDATE");
_Static_assert(P_SAVE    == ID_SAVE,    "pids.h drift: SAVE");
_Static_assert(P_SPAWN   == ID_SPAWN,   "pids.h drift: SPAWN");
_Static_assert(P_LIT2    == ID_LIT2,    "pids.h drift: LIT2");
#if defined(OVL_LOAD)
_Static_assert(P_LOAD    == ID_LOAD,    "pids.h drift: LOAD");
#endif
#endif
/* GUARDRAIL: pids.h is the ASSEMBLER's view of the SHIPPING image, and it HAD drifted: it said
 * `ID_BLKXFER 66 / ID_SPAWN 67` while the enum says 65 and 69 — the ids between BLKXFER and SPAWN were
 * missing from the file entirely. Nothing caught it, because the assembler that consumes pids.h is not built
 * and every static assert above names an id below 40. It surfaced only when removing FAULT shifted every
 * later id and SPAWN finally dispatched as the wrong word.
 * GUARDRAIL: no assert can guard this file, which is why there is a comment instead: the ids are
 * CONFIGURATION-DEPENDENT (a plain host build has no block primitives, so every id after them shifts; the
 * blocks host build runs a different P54 rung), so an assert that passes in the shipping build fails in the
 * next correct build. When you add, remove or reorder a primitive, re-derive pids.h FROM THE ENUM. */
_Static_assert(SD == 16, "dispatch.S assumes SD=16 for the stack wrap check");
_Static_assert(sizeof(VM) == 136, "dispatch.S hard-codes the VM layout");

/* ---- P54: the same-shape binary primitives, driven from one table ----
 * ADD SUB MUL AND OR XOR LSHIFT RSHIFT LT ULT all do `pop b; top = op(top, b)` and nothing else, yet each
 * pays its own 38-44 B copy of the pop/top-address/store sequence (measured from the shipping ELF, see
 * P54-ops/FINDINGS.md). One shared body plus a per-op leaf removes nine of those copies.
 * GUARDRAIL: this is a -D switch, not an edit, for P30's reason: the base build has to keep compiling to
 * the shipping .text byte for byte, or the delta stops being a measurement of this change.
 * GUARDRAIL: it must sit AFTER pids.h and the P_* enum (the leaves' slots are P_<id> - P_ADD and the
 * generated header asserts them) and BEFORE p33_cases.inc is included in vm_enter() — p54_subset.inc has
 * to define P31_SUBSET/P_HAVE_* before p31_cases.inc is reached, or both bodies for a converted token are
 * compiled and the second one wins silently. */
#if defined(P54_BINOPS)
#include "p54_subset.inc"
#include "p54_ops.h"
#endif

/* ---- input ---- */
static u8 tib[TIBSZ];
static u8 tl, ti;
static u8 errf;
static u32 savehere, savelatest;

/* ---- P1_TRACE: host-only diagnostic (never baked: the whole block is #ifdef HOST) --------------------
 * GUARDRAIL: a refusal and a not-found print the SAME text on this machine, because mkentry's refusal and
 * interpret()'s lookup failure both go through err() with PAD holding the token. Six probes were spent
 * guessing which one the phase hit. The fix is not better guessing: count refusals in a cell and dump the
 * machine state, plus a ring of the last parsed tokens, from INSIDE err() - i.e. BEFORE the rewind at the
 * end of interpret(), which is what erases the evidence in the first place.
 * GUARDRAIL: cost is zero on the chip. This whole section is compiled out of a bake, so it cannot appear in
 * .text or .rodata and cannot cost a byte of application space. Do not "share" it with the shipping build. */
#ifdef P1_TRACE
int p1_trace, p1_refusals;
static char p1_ring[12][32]; static int p1_n, p1_i;
static void p1_push(void)                      /* PAD holds the token just parsed */
{
    u8 n = rd8(PAD), k;
    for (k = 0; k < n && k < 31u; k++) p1_ring[p1_i][k] = (char)rd8(PAD + 1u + k);
    p1_ring[p1_i][k] = 0;
    p1_i = (p1_i + 1) % 12; if (p1_n < 12) p1_n++;
}
static void p1_dump(const char *why)
{
    int j;
    fprintf(stderr, "[P1 %s] HERE=%u LATEST=%u STATE=%u refusals=%d tokens:", why,
            rd32(V_HERE), rd32(V_LATEST), rd32(V_STATE), p1_refusals);
    for (j = p1_n; j > 0; j--) fprintf(stderr, " %s", p1_ring[(p1_i + 12 - j) % 12]);
    fprintf(stderr, "\n");
}
#endif

static void err(void)
{
    u8 i, n = rd8(PAD);
#ifdef P1_TRACE
    /* GUARDRAIL: dumped BEFORE the message and before interpret()'s rewind - taking it afterwards reports
     * the recovered state, which is exactly the information we already have from the prompt. */
    if (p1_trace) p1_dump("ERR");
#endif
    for (i = 0; i < n; i++) pl_emit(rd8(PAD + 1 + i));
    pl_emit('?'); pl_emit('\n');
    errf = 1;
}

/* parse next blank-delimited word into PAD (upper-cased); returns length */
/* GUARDRAIL: the source switch. LOAD used to call interpret() recursively from inside a primitive, which
 * (a) re-entered vm_enter and put the chip's ~327 B stack 9 B over on the deepest chain - measured, a block
 * containing a definition failed with an ambiguous `?` while a block containing only execution worked - and
 * (b) lost the rest of the line, because the nested interpret consumed the outer one's cursor. word() is the
 * ONLY reader of tib (checked: no parse/[CHAR]/['] variant exists in this engine), so switching sources here
 * is local: when the current source runs dry, a pending block refills tib chunk by chunk, and when the block
 * is exhausted the saved line continues exactly where it was. No recursion, no lost tail, no extra frame. */
#if defined(OVL_LOAD)
/* GUARDRAIL: how much of a block one pass delivers. On the chip this is TIBSZ-1 (96-1 = 95), and that is the whole
 * problem: a block is 128 B, so it always takes two passes and the boundary lands wherever TIBSZ says. The knob
 * exists so the HOST can simulate the chip's 95-byte pass while keeping a 128-byte tib - a host built at TIBSZ=96
 * cannot even load the prelude (line 3 is 99 chars: "line too long"), so the defect could never be reproduced there.
 * Default is the real thing, so a build that sets nothing behaves exactly as the chip does. */
#ifndef BLKPASS
#define BLKPASS (TIBSZ - 1)
#endif

static void blk_refill(void)
{
    u32 v = rd32(V_LOADB), blk, off, i, end;
    if (!v) return;
    blk = (v & 0xffu) - 1u;
    off = v >> 8;
    if (off >= BLKSZ) { wr32(V_LOADB, 0); return; }
    end = off + BLKPASS;
    if (end > BLKSZ) end = BLKSZ;
    if (end < BLKSZ) {                      /* not the last chunk: cut back to a token boundary */
        u32 k = end;
        while (k > off && rd8(BLKADR + k) > ' ') k--;
        if (k > off) end = k;
    }
    for (i = off; i < end; i++) {
        u8 c = rd8(BLKADR + i);
        tib[i - off] = (c >= ' ') ? c : ' ';
    }
    tib[end - off] = ' ';
#ifdef P1_TRACE
    if (p1_trace) fprintf(stderr, "[P1 REFILL] blk=%u off=%u end=%u loadb_after=%u\n", blk, off, end,
                          (end >= BLKSZ) ? 0u : ((blk + 1u) | (end << 8)));
#endif
    ti = 0; tl = (u8)(end - off + 1);
    wr32(V_LOADB, (end >= BLKSZ) ? 0u : ((blk + 1u) | (end << 8)));
}
#endif

static u8 word(void)
{
    u8 n = 0, c;
#if defined(OVL_LOAD)
    /* GUARDRAIL: refill in a LOOP, not once before the space-skip. blk_refill ends every pass by writing a space at
     * the cut, so the skip below can run to ti == tl: the old code then returned 0 with the block's remainder still
     * pending, the interpreter closed the line, and the leftover arrived during the NEXT line - measured as `;`
     * running inside the next command (ERR_STACK, and `42?42?42?...` in the worst case) and as a NAME parsed across
     * the boundary being lost outright (`CREATE NAMEX` with NAMEX past offset 95 answered NAMEX? because CREATE was
     * told the source was dry).
     * GUARDRAIL: no retry counter is needed. blk_refill either advances the offset (so the loop is bounded by
     * BLKSZ/BLKPASS passes) or clears V_LOADB, so this cannot spin - and the counter cost 13 bytes of pool, which
     * flash_safe refused (7869 > 7856). Tested by tests/block_boundary.sh at the chip's 96-byte pass. */
    for (;;) {
        while (ti < tl && tib[ti] <= ' ') ti++;
        if (ti < tl) break;                       /* a token is available */
        if (!rd32(V_LOADB)) break;                /* no block pending: end of source */
        blk_refill();                             /* the pass ended on padding: pull the remainder */
    }
#else
    /* GUARDRAIL: the blank-skip must exist on BOTH paths. Restructuring the block above deleted this branch, and
     * every token in a build without OVL_LOAD then began with a leading space - measured as 13 of 22 tests failing
     * at once. A refactor of the refill loop must keep this line, or say why it is no longer needed. */
    while (ti < tl && tib[ti] <= ' ') ti++;
#endif
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

/* ---- messages: ONE byte on the wire, the text lives on the HP core (msg_codes.h) ----
 * GUARDRAIL: every message the engine prints goes through msg(), never a string literal. The text cost
 * 104 B of the ULP's .rodata, the scarcest resource here, while the host has 32 MB of flash it cannot
 * spend; and a string literal per call site is a second copy of a message that the host must also know.
 * GUARDRAIL: msg() is the single emit path. Do not reintroduce a per-character string loop — the point
 * is that no message text and no text-walking code is left in the ULP image. */
#include "msg_codes.h"
static void msg(u8 code) { pl_emit((int)code); }
/* GUARDRAIL: variant (f) = (c)+(d). The two are independent: (c) removes a duplicated code-selection
 * table, (d) removes the repeated errf store. Measured together because a lever that only pays in
 * combination is a different claim from either alone, and the pool number must be the combined one. */
static void __attribute__((noinline)) errf_msg(u8 code) { msg(code); errf = 1; }

static u32 hash_pad(u8 n)
{
    u32 h = 5381u; u8 i;
    for (i = 0; i < n; i++) h = (h * 33u) + rd8(PAD + 1 + i);
    /* GUARDRAIL: the mask is the measurement, not a detail — djb2/m33 with this seed is collision-free
     * over the 85 baked names at 13 bits (and at 12, but not at 11: SAVE vs THEN). Changing the seed,
     * the multiplier or this mask invalidates that search: re-run tools/hashsearch.py on a fresh
     * -DP54_NAMES dump, then re-bake — the -d path re-checks the stored keys pairwise and exits 3. */
    /* GUARDRAIL: the width is a MEASURED choice, and 12 bits is what the ceiling needs. The entry is
     * imm(1) | xt/2(11) | hash(12) = 24, so xt can reach 4094 — without the 11th xt bit, MEMSZ was capped at
     * 2048 and any further text saving stopped being bankable as app space. djb2/m33 with this seed was
     * measured collision-free at 13 AND at 12 bits (but not at 11: SAVE vs THEN). Changing the seed, the
     * multiplier or this mask invalidates that: re-run tools/hashsearch.py on a fresh -DP54_NAMES dump and
     * re-bake — the -d path re-checks the stored keys pairwise and exits 3 on a collision. */
    return h & 0x0fffu;                      /* 12 bits: 11 for xt/2 and 1 for the immediate flag */
}

static u16 find(u8 n, u8 *imm)
{
    u32 hs, h;
    u8 b0, b1;
    if (!n) return 0;
    hs = hash_pad(n);
    /* GUARDRAIL: fixed stride, no links, byte reads (see the P54 note above: an entry at HDRTOP-3k is
     * odd for half the k, so rd16/rd32 would trap). `mem[h]` is unchecked on purpose: the loop bounds
     * h + 3 <= HDRTOP and _Static_assert(HDRTOP <= MEMSZ) prove h + 2 < MEMSZ, which is exactly the
     * guarantee rd8() re-tests per byte — three tests on the input path would cost more than the byte
     * reads they guard. Do not use this idiom for an address the loop does not bound. */
    for (h = rd32(V_LATEST); h + HDRSZ <= (u32)HDRTOP; h += HDRSZ) {
        /* The 8-bit filter first: a miss is one lbu, which is what all but one of these iterations is.
         * P46 measured this loop as the single largest cost of typing at this REPL. byte 2 holds hash
         * bits 5..12; byte 1 holds hash bits 0..4 in its top 5 bits. */
        if (mem[h + 2u] != (u8)(hs >> 4)) continue;
        b1 = mem[h + 1u];
        if ((b1 >> 4) != (u8)(hs & 0x0fu)) continue;
        b0 = mem[h];
#ifdef P31_TRACE
        if (p31_nhit < (int)(sizeof p31_hits / sizeof p31_hits[0])) p31_hits[p31_nhit++] = h;
#endif
        /* xt/2 is bits 1..10, i.e. bits 1..7 in b0 and bits 0..2 in b1's low bits; xt is that doubled.
         * GUARDRAIL: double LAST by shifting the halves up by 8, not by masking a doubled value — an
         * earlier `& 0x7fe` form cleared xt/2's bit 0 and every word at xt 2 mod 4 dispatched one
         * halfword down (measured: SPAWN resolved to xt 94 while its own header said 190, and nothing
         * printed `?` — the wrong-word silence this dictionary exists to avoid). */
        *imm = (u8)(b0 & 1u);
        return (u16)((((u32)(b1 & 0x0fu)) << 8) | (b0 & 0xfeu));
    }
    return 0;
}

/* GUARDRAIL: the base is 10, always, and this parser no longer reads V_BASE. The slot was written ONCE at
 * boot and read only here — there is no BASE/HEX/DECIMAL word, so a user could never change it — which made
 * the `A`..`Z` digit path unreachable (every letter is 10..35, i.e. >= the only base it could have been), and
 * the interpreter's fallback number() for a non-numeric token unreachable for the same reason. All three went
 * together, and the 4-byte slot went with them: PAD now starts at 12 and DICT at 44.
 * GUARDRAIL: if base switching is ever wanted it comes back as a real feature (a BASE word plus this
 * multiplier), not by re-adding a variable that nothing writes. */
static u8 number(u8 n, u32 *out)
{
    u32 v = 0; u8 i = 0, neg = 0, c;
    if (n > 1 && rd8(PAD + 1) == '-') { neg = 1; i = 1; }
    for (; i < n; i++) {
        c = rd8(PAD + 1 + i);
        if (c < '0' || c > '9') return 0;
        v = v * 10u + (u32)(c - '0');
    }
    *out = neg ? 0u - v : v;
    return 1;
}

static void cw(u16 v) { u32 h = rd32(V_HERE); wr16(h, v); wr32(V_HERE, h + 2); }
/* GUARDRAIL: `v <= 0xffff` is the halfword test, and it deliberately does NOT use a signed test: -1 is
 * 0xffffffff, which needs all four operand bytes, so a signed comparison would emit a 4-byte literal that
 * LIT2 would read as 0xffff and the stack would quietly hold the wrong number. */
static void clit(u32 v)
{
    if (v <= 0xffffu) { cw(XT_PRIM(P_LIT2)); cw((u16)v); }
    else { cw(XT_PRIM(P_LIT)); cw(v); cw(v >> 16); }
}
/* GUARDRAIL: a4() is GONE. It rounded V_HERE up to 4 before a cell was written, and every reader of that
 * cell is either byte-wise (wr32/rd32 are two rd16 halves) or an `rd16`, which needs only that the address
 * be EVEN. V_HERE is always even — every writer adds 2 (cw, mkhdr_pad's x+2) or 4 (COMMA) — and mkhdr_pad
 * refuses an odd x outright, so the round-up could only ever fire on V_HERE == 2 mod 4 and waste 2 bytes.
 * GUARDRAIL: this is NOT permission to store a cell at an ODD address: rd16 on this target is a real 16-bit
 * load and the ALIGN_TRAP build halts on an odd one. Even is the requirement; 4 was an assumption.
 */

/* build a header from the name currently in PAD; returns the xt */
/* ---- P54: name dump for the hash search (host bake only) ----
 * GUARDRAIL: the vocabulary that the hash has to be injective over is the set of names the ENGINE
 * actually interns, not the set a regex over the prelude thinks it sees — a second derivation of the
 * same list is exactly what R6 forbids, and a name missed here is a collision the search never sees.
 * So the list comes out of mkhdr_pad, the one place a name becomes a header. */
#ifdef P54_NAMES
#include <stdio.h>
#endif

/* GUARDRAIL: the xt field of a header is 11 bits and a real address is ALWAYS EVEN (mkhdr_pad asserts it
 * below), so bit 0 of that field was dead. It now MEANS something: an odd field holds 2*id+1, i.e. "this
 * token is a primitive id, not an address". That is what lets a primitive live in the dictionary with NO
 * code field in mem[] — the 70 boot primitives used to consume 2 B each of the code area before the
 * prelude, and removing those 140 B moves every colon word down into application space.
 * GUARDRAIL: the token is decoded in exactly ONE place (vm_enter's loop top), and EXEC re-enters that same
 * top, so `' + EXEC` works with an odd token. Any new code that fetches a code field by hand would read an
 * address that holds no cell and dispatch whatever followed it. */
static u16 mkentry(u16 tok, u8 imm)
{
    u32 hs = hash_pad(rd8(PAD)), h = rd32(V_LATEST) - HDRSZ, v;
    /* GUARDRAIL: mask with 0xFFE, not 0x7FF. The xt field is bits 1..11 of the entry and bit 0 is the imm
     * flag, so a token keeps its full 12 bits here; masking to 11 bits folded bit 11 and turned the PRIM_TAG
     * encoding back into a small ADDRESS (measured: `2 3 + .` answered an error on line 1, because every
     * primitive's token decoded to xt 1992, a code field that does not exist). */
    /* GUARDRAIL: refuse an overlay definition whose 12-bit hash matches a RESIDENT name, before writing the
     * entry. Only the hash is stored, so a collision cannot be distinguished from redefining the same word -
     * refusing is honest and renaming is the operator's fix. The scan starts at V_SEAL (the sealed V_LATEST)
     * and runs UP: overlay headers sit below it because they were written after the seal. Measured
     * false-positive rate: ~2.3 % per definition (98 resident words in a 4 096-value band).
     * GUARDRAIL: this lives HERE, not in a helper called from mkhdr_pad. The helper recomputed hash_pad(PAD)
     * at a point where PAD no longer held the name, so `hs` was the hash of an EMPTY name - 1285, which is
     * LOAD's hash - and every definition after SEAL was refused with ERR_DICT. The hash that matters is the
     * one about to be stored, i.e. this local.
     * GUARDRAIL: the scan starts at V_LATEST, not at V_SEAL. V_SEAL is only the on/off gate; starting there
     * compared the new name against RESIDENT headers alone, so two names colliding inside the SAME overlay were
     * invisible - and at ~2.4 % per name a 40-name phase has a ~62 % chance of at least one collision, so an
     * intra-overlay one would routinely hide among the loud ones. V_LATEST is the newest existing header, so
     * scanning up from it covers the overlay's own entries AND every resident one.
     * GUARDRAIL: the refusal goes through err(), which prints the offending name from PAD and a '?'. It used to
     * be errf_msg(MSG_ERR_DICT) and printed only "ERR_DICT" - a message that names the failure but not the word,
     * in a situation where renaming the word is the whole fix. Do not "improve" this back into a fixed string:
     * the token is free here, a new message is .rodata. */
    if (rd32(V_SEAL)) {
        u32 s;
        for (s = rd32(V_LATEST); s + HDRSZ <= (u32)HDRTOP; s += HDRSZ) {
            if (mem[s + 2u] != (u8)(hs >> 4)) continue;
            if ((mem[s + 1u] >> 4) != (u8)(hs & 0x0fu)) continue;
#ifdef P1_TRACE
            /* GUARDRAIL: the counter is the discriminator the message cannot be. */
            p1_refusals++; if (p1_trace) p1_dump("REFUSE");
#endif
            err();                          /* names the token, then '?' */
            return 0;
        }
    }
    v = ((hs << 12) | ((u32)tok & 0xffeu)) | (u32)(imm & 1u);
    /* GUARDRAIL: printed BEFORE the header write so a bake that runs out of room still names the word that
     * broke it; a dump taken after the write would silently miss the last entry. */
#ifdef P54_NAMES
    { u8 k, nn = rd8(PAD); fprintf(stderr, "NAME "); for (k = 0; k < nn; k++) fputc(rd8(PAD + 1 + k), stderr);
      fprintf(stderr, "\n"); }
#endif
    wr16(h, (u16)v); wr8(h + 2u, (u8)(v >> 16));
    wr32(V_LATEST, h);
    return tok;
}

/* build a header from the name currently in PAD, with a 2-byte code field at the xt; returns the token */
static u16 mkhdr_pad(u8 cf, u8 imm)
{
    u32 x = rd32(V_HERE), h = rd32(V_LATEST) - HDRSZ;
    /* GUARDRAIL: the room check precedes BOTH writes. Once the code area has been written over the header
     * area the damage is a wrong-word dispatch at some later line, not a failure here. */
    /* GUARDRAIL: one exit for both dictionary-state failures. They carried the same message code and the
     * same recovery, so two errf_msg call sites only cost bytes; the distinct reasons stay in the comments
     * below rather than in the code. */
    /* GUARDRAIL: no `x >= 2048u` test here. The line above proves x < h <= HDRTOP <= MEMSZ, and
     * _Static_assert(MEMSZ <= 4094) pins the other end, so the bound was dead code — the assert is what
     * keeps it honest, and it fires at compile time instead of costing a compare per definition. */
    if (x + 2u > h || (x & 1u)) { errf_msg(MSG_ERR_DICT); return 0; }
    /* GUARDRAIL: an odd x would make the header field collide with the primitive encoding above (odd means
     * "id"), i.e. a colon word would dispatch as some primitive with no trace anywhere. Nothing but cw()'s
     * +2 and a4()'s round-up-to-4 writes V_HERE, so odd is an engine bug, not user input — but this is the
     * only place an offset becomes a header field, so this is where it has to fail.
     * GUARDRAIL: `v` is a 24-bit little-endian value, written as wr16 + wr8. A single wr32 at h would
     * clobber h+3, which is the already-written entry ABOVE (entries grow DOWN), and a wr32 at h - 1
     * pays one byte of the free gap to keep the write word-shaped — measured at +72 B of .text, which
     * is a bad trade for one byte of app space. */
    /* GUARDRAIL: mkentry runs FIRST and the code field is written only if it succeeded. The order is the
     * whole point: the seal check inside mkentry refuses a redefinition of a resident name, and the previous
     * order (wr16 + V_HERE first) left 2 bytes written and HERE advanced by 2 on a refused definition -
     * measured as `HERE bh @ = .` answering 0 instead of -1. mkentry signals refusal through errf, which is
     * why the return value is not inspected. */
    { u16 t = mkentry((u16)x, imm);
      if (errf) return 0;
      wr16(x, cf);                                /* the code field lives at the xt, in the code area */
      wr32(V_HERE, x + 2);
      return t; }
}

/* a BOOT PRIMITIVE: no code field at all, the token is 2*id+1 (see the guardrail above) */
static u16 mkhdr_prim(u8 cf, u8 imm)
{
    /* GUARDRAIL: only the header area can be collided with here — a primitive allocates nothing in the code
     * area — but the test must still exist: it is what turns a full dictionary into a named error instead
     * of headers written over live code. */
    if (rd32(V_HERE) > rd32(V_LATEST) - HDRSZ) { errf_msg(MSG_ERR_DICT); return 0; }
    return mkentry((u16)((PRIM_TAG - 2u * (u32)cf) | (u32)(imm & 1u)), imm);
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
/* GUARDRAIL: the whole task machinery is behind P43_TASKS, declarations included. Guarding only the functions saved 264 B
 * of .text but left 272 B of .bss (`tskvm`) allocated, because the arrays were declared unconditionally - the linker kept
 * them even with every reference dead. With tasks undefined there is no SPAWN (documented as broken: it loses the REPL)
 * and the two VM records plus the states are unreachable, so they must not exist. */
#if defined(P43_TASKS)
#ifndef NTSK
#define NTSK 2
#endif
/* GUARDRAIL: no `entry` field. It stored the word's xt and was read by nothing — the task's start address
 * already lives in vm.W, which is what vm_task_init sets and what the dispatcher resumes from. Removing the
 * field also removes its store (padding absorbed the bytes, so this is a text win, not a bss one). */
/* GUARDRAIL: the VM and its state are separate arrays, not a struct. `{ VM vm; u8 state; }` cost 140 B per
 * slot because VM is 136 and the u8 padded it to a 4-byte boundary — 4 B of pure padding times NTSK. Two
 * arrays keep every VM 136-aligned and put the states in one byte each. */
static u8 tskstate[NTSK];   /* 0 free, 1 ready, 2 done */
static VM tskvm[NTSK];
static int cur = -1;                  /* -1 = run() is the outer interpreter, not a task */
#endif /* defined(P43_TASKS) */
/* GUARDRAIL: the switch counters are gone (vm_switches, vm_sw_taskexit, vm_sw_first). Each was
 * incremented once per switch and read by NOTHING — not the boot banner, not the suite, not the bench, not
 * any tool — so each cost a load, an add and a store per switch plus 4 B of .bss. Same class as the depth
 * counters (P56): an increment whose value nobody reads is pure cost. `vm_sw_pause`, `vm_sw_fault`,
 * `vm_faults` and `vm_faults_left` stay: they belong to the PAUSE/FAULT path, which is compiled out under
 * P33_NOPAGE but is functional when that build is used. */
/* GUARDRAIL: vm_sw_pause is GONE. It was incremented on every cooperative PAUSE and read by NOTHING —
 * neither the boot banner, the suite, the bench, nor any tool. `vm_sw_fault` and `vm_faults` stay: they are
 * incremented in the FAULT body, which is compiled out under P33_NOPAGE but live in that build, and
 * `vm_faults_left` there is functional state (how many injected faults remain), not a counter. */
/* GUARDRAIL: vm_sw_fault, vm_faults and vm_faults_left are GONE with the FAULT word. FAULT was a
 * paging-era primitive: under P33_NOPAGE nothing ever set vm_faults_left nonzero, so its body reduced to
 * `if (0) { ... } goto tail;` — a word in the dictionary that could not do anything. Removing it takes the
 * entry from the dispatch table, its case body, its 3 state words, and its header plus code field with it.
 * GUARDRAIL: it is deleted from p31_prims.inc, not just gated, because p54_gen.py derives the P_HAVE_* subset
 * list from that file — gating one place and leaving the other is how a word comes back on regeneration. */
/* Depth of the C calls into the interpreter. A switch must NOT change it: if PAUSE or a
 * fault returned through C, a task that yielded mid-word would unwind to its caller and the
 * resume would start a second vm_enter. Measured so the claim is not an assertion. */
/* GUARDRAIL: vm_depth counts ENTRIES to vm_enter, not Forth nesting — DOCOL and EXEC continue the same
 * dispatch loop instead of recursing, so this is 1 during any word and the max it records is 1. The real
 * nesting limit is SD 16 on the data/return stacks, enforced by PUSH/RPUSH and reported as ERR_STACK.
 * Nothing live reads these two: the host harness, the suite, the bench and every tool ignore them (only
 * archived copies of the engine mention them). They cost a load, an add, a compare and a conditional store
 * on every word call plus two stores per exit, which is why they are gated rather than shipped.
 * GUARDRAIL: keep the flag, not just the deletion — P13's depth evidence is reproducible only with
 * -DVM_DEPTH_STATS, so the measurement stays available instead of being quietly lost. */
#if defined(VM_DEPTH_STATS)
static int vm_depth, vm_max_depth;
#define VMD_ENTER()  (vm_depth++, (vm_depth > vm_max_depth ? (void)(vm_max_depth = vm_depth) : (void)0))
#define VMD_LEAVE()  (vm_depth--)
#else
#define VMD_ENTER()  ((void)0)
#define VMD_LEAVE()  ((void)0)
#endif
/* GUARDRAIL: the `vm_trace` hook is deleted, not just unreferenced. Nothing in the tree ever assigned it, so
 * the call site cost a load, a branch and an indirect call per task switch to invoke a function that was
 * always null. P29's rule — a hook that nothing calls is a stub — applies one step further: a hook nothing
 * SETS is a branch that always fails. Re-add it with a setter when something actually needs it. */

#if defined(P43_TASKS)
static int vm_next_ready(int from)
{
#if NTSK == 2
    /* GUARDRAIL: unrolled on purpose. The general form below computes `(from + i) % NTSK` per slot; at
     * NTSK 2 that is a loop plus a modulo for two candidates, and the whole scheduler runs on every wake.
     * The unrolled order is identical to the loop's: (from+1)&1 is the OTHER slot, then `k ^ 1` is the
     * caller's own slot, and for from == -1 that is 0 then 1 — measured, not derived from the modulo:
     * tests/ntsk.fs and the on-device two-task run both exercise spawn-spawn-run. */
    int k = (from + 1) & (NTSK - 1), o = k ^ (NTSK - 1);
    if (tskstate[k] == 1) return k;
    if (tskstate[o] == 1) return o;
    return -1;
#else
    int k, i;
    for (i = 1; i <= NTSK; i++) {
        k = (from + i) % NTSK;
        if (tskstate[k] == 1) return k;
    }
    return -1;
#endif
}

#if defined(P30_HANDCOPY)
/* ---- P30 D: hand-written VM copy and task zeroing ----
 * GUARDRAIL: `tskvm[from] = *V` is a 136 B struct copy, and at -Os rv32imc GCC emits a libgcc `memcpy`
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
#ifdef VM_TASK_TRACE
#include <stdio.h>
/* GUARDRAIL: host-only flight recorder for F-122: it prints the LIVE machine and every task record around
 * a switch, so "which record did the save land in" is READ rather than argued. Behind a flag because it
 * costs .text, and because a trace inside the scheduler is instrumentation inside the thing it measures. */
static void vm_dump(const char *tag, int k)
{
    if (k < 0)
        fprintf(stderr, "[%-6s] live   W=%u IP=%u SP=%u RSP=%u cur=%d\n", tag,
                (unsigned)V->W, (unsigned)V->IP, V->SP, V->RSP, cur);
    else
        fprintf(stderr, "[%-6s] tsk%d   state=%u W=%u IP=%u SP=%u RSP=%u\n", tag, k, tskstate[k],
                (unsigned)tskvm[k].W, (unsigned)tskvm[k].IP, tskvm[k].SP, tskvm[k].RSP);
}
#define VMDBG(tag, k) vm_dump(tag, k)
#else
#define VMDBG(tag, k) ((void)0)
#endif

static void vm_switch(int next)
{
    int from = cur;    VMDBG("enter", -1); VMDBG("enter", 0); VMDBG("enter", 1);
#ifdef VM_TASK_TRACE
    fprintf(stderr, "[layout] sizeof(VM)=%u sizeof(TSK)=%u &live=%p &tsk0=%p &tsk1=%p V=%p\n",
            (unsigned)sizeof(VM), (unsigned)sizeof(tskstate), (void*)&vm_live, (void*)&tskvm[0], (void*)&tskvm[1], (void*)V);
#endif
#if defined(P30_HANDCOPY)
    /* GUARDRAIL: the struct copy compiles to a libgcc memcpy *call* on rv32imc at -Os (232 B, P29), so
     * copy word by word here — and copy the stacks by element, not by memcpy, or the saving is zero. */
    if (from >= 0) vm_copy(&tskvm[from], V);
#else
    if (from >= 0) tskvm[from] = *V;    /* struct copy = the whole switch point */
#endif
    cur = next;
#if defined(P30_HANDCOPY)
    if (next >= 0) vm_copy(V, &tskvm[next]);
#else
    if (next >= 0) *V = tskvm[next];
    VMDBG("after", -1); VMDBG("after", 0); VMDBG("after", 1);
#endif
}

/* A switched-in task has no C caller to return to, so ip == 0 means the task itself
 * is finished: retire it and give the CPU to the next ready task. */
static int vm_task_leave(void)
{
    int nx;
    if (cur < 0) return 0;               /* outer interpreter: a plain C return is right */
    tskstate[cur] = 2;
    nx = vm_next_ready(cur);
    /* P29: the fourth hook, called for real when the last task retires. GUARDRAIL: keep this call on
     * the retire path — a hook that nothing calls is a stub, and a stub's bytes are not the layer's. */
    /* GUARDRAIL: pl_halt(0) here was written when tasks were the *only* driver: on the last retire
     * the machine was expected to stop. With a REPL above them, halting on the last task exit kills
     * the console too — the ULP stops and the host reads silence. Return to C instead, with cur back
     * to -1 so the outer interpreter is the machine again. */
    if (nx < 0) { cur = -1; return 0; }   /* last task: unwind to the C driver */
    vm_switch(nx);
    return 1;
}

static void vm_task_init(int k, u16 xt)
{
    int j;
    /* GUARDRAIL: typed four-at-a-time zeroing, EXACTLY sizeof(VM) bytes. The previous form walked a u32*
     * for sizeof(VM)/4 = 34 words in groups of four, so it wrote 36 words — two words (8 B) PAST the record.
     * That was invisible only because the old TSK struct had 4 B of trailing padding per slot and the overrun
     * landed in it; the moment the VM and its state moved to separate arrays (P64) the overrun started
     * zeroing the NEXT task's record: measured as `tasks.fs` printing "2" and `tasks_pause.fs` printing "34"
     * (only the last-spawned task ever ran) and a third SPAWN no longer being refused.
     * GUARDRAIL: DS/RS are u32 arrays so unrolling them four at a time is legal AND cheap; the u8/u16 scalars
     * are assigned by name. Do not go back to a word loop over the whole struct. */
    for (j = 0; j < SD; j += 4) {
        tskvm[k].DS[j] = tskvm[k].DS[j+1] = tskvm[k].DS[j+2] = tskvm[k].DS[j+3] = 0u;
        tskvm[k].RS[j] = tskvm[k].RS[j+1] = tskvm[k].RS[j+2] = tskvm[k].RS[j+3] = 0u;
    }
    tskvm[k].SP = 0; tskvm[k].RSP = 0;
    tskvm[k].W = xt; tskvm[k].IP = 0;  /* ip 0 = the task's outermost word ends via EXIT */
    tskstate[k] = 1;
}
#else
/* GUARDRAIL: VMDBG is defined inside the guarded block, so with tasks off the EXIT/PAUSE bodies lost their no-op macro
 * and the build failed with "implicit declaration of VMDBG" - a macro that vanishes is a compile error, not a silent
 * default. Give the no-task build an explicit no-op instead. */
#define VMDBG(tag, k) ((void)0)
#endif /* defined(P43_TASKS) */

#if defined(BLKPRIM)
/* ---- R5: BLOCK / UPDATE / SAVE as C primitives ---------------------------------
 * The Forth layer measured 530 B of dictionary, 146 of it constants and CREATE'd cells that existed only
 * so Forth could say `BLKERR @`. As primitives the contract is identical — a failed BLOCK leaves its named
 * code on the stack and does NOT hand back the buffer — and the cost is three headers.
 * GUARDRAIL: the failures are NAMED, not silent. GUARDRAIL: their text lives on the host (msg_codes.h):
 * a string per message here would put back the .rodata the message-code change removed. */
static u32 blkvars[2];                  /* 0 blkn, 1 blkdirty */
/* GUARDRAIL: there is no BLK_VBLKERR slot. It was written on a refused block and on every xfer result and
 * read by NOBODY — the error reaches Forth as the pushed status and the host as the message code, so the
 * cached copy was pure cost (two stores plus 4 B of .bss). Same audit as the depth/switch/line counters. */
#define BLK_VBLKN   0u
#define BLK_VBLKDRT 1u

static void blk_errmsg(i32 st)
{
    /* GUARDRAIL: the six-way chain used to store the code six times behind a 24 B .rodata jump table
     * (26 B of dispatch + 36 B of `li`+`j`); choosing the code first and emitting once measures −48 B
     * of pool (P54-fail). The predicates and the UNNAMED fallback are the shipped ones. */
    u8 c = MSG_ERR_UNNAMED;
    if (st == BK_BUSY)          c = MSG_ERR_BUSY;
    else if (st == BK_NOSERVER) c = MSG_ERR_NOSERVER;
    else if (st == BK_CRC)      c = MSG_ERR_CRC;
    else if (st == BK_BUFOVER)  c = MSG_ERR_BUFOVER;
    /* GUARDRAIL: BK_RANGE was missing from this chain, so a block number past the store's end reached
     * Forth as ERR_UNNAMED -5: the status was right and the name was not. The host now nacks with 5
     * (magnitude of -5) for "no such block" and that name is what tells the operator to stop asking
     * for block 128 of an 128-block store. */
    else if (st == BK_RANGE)    c = MSG_ERR_RANGE;
    else if (st == BK_DIRTY)    c = MSG_ERR_DIRTY;
    msg(c);
}

static void p_blk_block(void)               /* ( n -- addr | code ) */
{
    i32 n = (i32)POP(), st;
    if (n < 0) { msg(MSG_ERR_RANGE); PUSH((u32)BK_RANGE); return; }
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
    if (st == BK_OK) { blkvars[BLK_VBLKDRT] = 0u; PUSH(BLKADR); return; }
    blk_errmsg(st); PUSH((u32)st);
}
static void p_blk_update(void) { blkvars[BLK_VBLKDRT] = 0xffffffffu; }
/* GUARDRAIL: LOAD arms the SOURCE SWITCH instead of interpreting the block itself. It fetches the block once
 * (so the window holds it) and stores the cursor in V_LOADB; word() then feeds those tokens to the SAME
 * interpreter that is already running. That is what removes the extra interpret/vm_enter frame (the chip's
 * ~327 B stack was 9 B over on the deepest chain), keeps the rest of the line alive, and makes an error inside
 * the block unwind the outer line instead of a nested one.
 * GUARDRAIL: BLOCK called from overlay text still clobbers the window - the fetch happens once, here, and a
 * later BLOCK replaces the remaining chunks. Keep data use out of overlay source.
 * GUARDRAIL: repl_blk_req must bracket the xfer, exactly as p_blk_block and p_blk_save do. Without it the read
 * is never serviced: measured on the chip, the first overlay token read garbage while the SAVE just before it
 * (which sets the flag) worked fine. */
static void p_load(void)                    /* ( blk -- ) arm a block as the interpreter's source */
{
    u32 n = POP();
    i32 st;
    /* GUARDRAIL (NOT ENFORCED YET - see docs/15-overlays.md): re-arming while V_LOADB is set SILENTLY SKIPS a block.
     * `8 LOAD 9 LOAD` on one line looks fine and drops block 8, because the rest of the current line runs before the
     * armed block; the same is true of `8 OVL 2 OVL` inside a colon word. The fix is a named error on re-arm, but
     * it invalidates every test whose loop arms twice - those loops were themselves silently skipping blocks - so it
     * lands together with those rewrites, one arm per line, not before them.
     */
    repl_blk_req = 1u;
    st = blk_xfer(n, BLK_READ);
    repl_blk_req = 0u;
    if (st != BK_OK) { blk_errmsg(st); errf = 1; return; }
    wr32(V_LOADB, n + 1u);                  /* offset 0: word() pulls the first chunk */
}

static void p_blk_save(void)                /* ( -- st ) */
{
    i32 st;
    if (blkvars[BLK_VBLKDRT] == 0u) { PUSH(0u); return; }
    repl_blk_req = 1u;
    st = blk_xfer(blkvars[BLK_VBLKN], BLK_WRITE);
    repl_blk_req = 0u;
    if (st == BK_OK) blkvars[BLK_VBLKDRT] = 0u;
    PUSH((u32)st);
}
#endif

static void vm_enter(void);

/* Host driver: give each ready task a turn until all are done. */
/* Spawn by name: parse the next word out of tib, resolve it, take the first free slot.
 * GUARDRAIL: named failures only — an unknown name or a full task table must report through err(),
 * never silently do nothing, or a script that spawns three tasks appears to work with one. */
#if defined(P43_TASKS)
static int vm_spawn_name(void)
{
    int k;
    u8 n, im; u16 xt;
    n = word();
    if (!n) { err(); return -1; }
    xt = find(n, &im);
    if (!xt) { err(); return -1; }
    for (k = 0; k < NTSK; k++) if (tskstate[k] != 1) break;
    /* GUARDRAIL: err() prints the word in PAD, which here is the NAME BEING SPAWNED — so a full table
     * reported `TC?` and looked exactly like an unknown word (the same confusion that made the block
     * id-drift present as a bare `?`). A full table is its own failure and must say so. */
    /* GUARDRAIL: variant (f) — (d) applied. */
    if (k >= NTSK) { errf_msg(MSG_ERR_TASKS); return -1; }
    vm_task_init(k, xt);
    return k;
}

static void vm_run_tasks(void)
{
    int nx = vm_next_ready(cur);
    if (nx < 0) return;
    vm_switch(nx);                       /* cur -1 -> first task; saves nothing, loads it */
    vm_enter();
    while (vm_next_ready(cur) >= 0) vm_enter();
}
#endif /* defined(P43_TASKS) */

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
    /* GUARDRAIL: w and ip are u16 FIELDS of the VM struct, so every token used to read and write them in
     * memory — twice per dispatch, plus once per body that touches ip (LIT, BRANCH, ZBRANCH, DOCOL, EXIT,
     * EXEC). They are hoisted into locals here and flushed only where the machine actually leaves: at a task
     * switch and at a return. GUARDRAIL: EVERY exit path must VM_FLUSH first — the next vm_enter resumes from
     * V->IP, so an unflushed return resumes at the previous token and silently re-executes it.
     * GUARDRAIL: vm_task_leave() copies V (vm_switch saves the current task and loads the next), so it needs
     * a flush before and a reload after; a reload is not optional, because it overwrites the very fields the
     * locals shadow. */
    u16 lw = V->W, lip = V->IP;
    /* GUARDRAIL: #undef before redefining. Redefining w/ip silently produced two compiler warnings ("w
     * redefined") on every build, and a warning nobody reads is how a real redefinition goes unnoticed. The
     * originals are restored after the function so the file's meaning is unchanged outside it. */
#undef w
#undef ip
#define w  lw
#define ip lip
#define VM_FLUSH()   (V->W = lw, V->IP = lip)
#define VM_RELOAD()  (lw = V->W, lip = V->IP)
    VMD_ENTER();
    /* P57: disp_tbl maps a primitive id to its case label. The ENTRY WIDTH is per-build, because the
     * saving is only legal where the whole function fits in a 16-bit span:
     *   ULP  : u16 offset from L_BAD — .srodata 2 B per entry, `lhu` + `add` + `jalr`.
     *   HOST : a plain pointer. The x86-64 build of this same function is far larger than 64 KB, and a
     *          truncated offset there is a jump into nowhere — measured: the bake segfaulted.
     * GUARDRAIL: one entry per LABEL OCCURRENCE. A line can carry two labels (`L_P_TICK: L_P_BTICK:`) and
     * an id can appear twice (p31 body gated off by p54_subset.inc, plus the P54 arm) under mutually
     * exclusive guards. Harvesting only the first label per line left BTICK with no entry, and the symptom
     * was `[']?` while baking: find() succeeded and the DISPATCH fell to L_BAD.
     * GUARDRAIL: every slot defaults to L_BAD, never to 0 — 0 is a valid ULP offset (it means L_BAD).
     */
#ifdef HOST
    typedef const void *disp_ent_t;
#define DISP_ENT(l)  ((const void *)&&l)
    static const disp_ent_t disp_tbl[P_COUNT] = {
        [0 ... P_COUNT - 1] = DISP_ENT(L_BAD),
#else
    typedef u16 disp_ent_t;
#define DISP_ENT(l)  ((u16)(&&l - &&L_BAD))
    static const disp_ent_t disp_tbl[P_COUNT] = {
        [0 ... P_COUNT - 1] = DISP_ENT(L_BAD),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_ADCG)
        [P_ADCG] = DISP_ENT(L_P_ADCG),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_ADD)
        [P_ADD] = DISP_ENT(L_P_ADD),
#endif
#if P54_BINOPS >= 1
        [P_ADD] = DISP_ENT(L_P_ADD),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_AND)
        [P_AND] = DISP_ENT(L_P_AND),
#endif
#if P54_BINOPS >= 4
        [P_AND] = DISP_ENT(L_P_AND),
#endif
#if defined(P33_BLOCK)
        [P_BLKXFER] = DISP_ENT(L_P_BLKXFER),
#endif
#if defined(BLKPRIM)
        [P_BLOCK] = DISP_ENT(L_P_BLOCK),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_BRANCH)
        [P_BRANCH] = DISP_ENT(L_P_BRANCH),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_BSLASH)
        [P_BSLASH] = DISP_ENT(L_P_BSLASH),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_TICK)
        [P_BTICK] = DISP_ENT(L_P_BTICK),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_CCOMMA)
        [P_CCOMMA] = DISP_ENT(L_P_CCOMMA),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_CFETCH)
        [P_CFETCH] = DISP_ENT(L_P_CFETCH),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_COLON)
        [P_COLON] = DISP_ENT(L_P_COLON),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_COMMA)
        [P_COMMA] = DISP_ENT(L_P_COMMA),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_CONSTANT)
        [P_CONSTANT] = DISP_ENT(L_P_CONSTANT),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_CREATE)
        [P_CREATE] = DISP_ENT(L_P_CREATE),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_CSTORE)
        [P_CSTORE] = DISP_ENT(L_P_CSTORE),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_DIVMOD)
        [P_DIVMOD] = DISP_ENT(L_P_DIVMOD),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_DO)
        [P_DO] = DISP_ENT(L_P_DO),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_DOCOL)
        [P_DOCOL] = DISP_ENT(L_P_DOCOL),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_DOCON)
        [P_DOCON] = DISP_ENT(L_P_DOCON),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_DOTQ)
        [P_DOTQ] = DISP_ENT(L_P_DOTQ),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_DOVAR)
        [P_DOVAR] = DISP_ENT(L_P_DOVAR),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_DROP)
        [P_DROP] = DISP_ENT(L_P_DROP),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_DUP)
        [P_DUP] = DISP_ENT(L_P_DUP),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_EMIT)
        [P_EMIT] = DISP_ENT(L_P_EMIT),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_EXEC)
        [P_EXEC] = DISP_ENT(L_P_EXEC),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_EXIT)
        [P_EXIT] = DISP_ENT(L_P_EXIT),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_FAULT)
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_FETCH)
        [P_FETCH] = DISP_ENT(L_P_FETCH),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_GPIOG)
        [P_GPIOG] = DISP_ENT(L_P_GPIOG),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_GPIOS)
        [P_GPIOS] = DISP_ENT(L_P_GPIOS),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_I)
        [P_I] = DISP_ENT(L_P_I),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_INVERT)
        [P_INVERT] = DISP_ENT(L_P_INVERT),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_J)
        [P_J] = DISP_ENT(L_P_J),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_KEY)
        [P_KEY] = DISP_ENT(L_P_KEY),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_KEYQ)
        [P_KEYQ] = DISP_ENT(L_P_KEYQ),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_LIT)
        [P_LIT] = DISP_ENT(L_P_LIT),
#endif
        /* GUARDRAIL: no P_HAVE_ guard. LIT2 is not a P54-converted op — it has no kernel arm — so the
         * subset gate must not be able to drop its slot while cw() keeps emitting its token: that would
         * dispatch L_BAD and every literal in the image would report a corrupt token. */
        [P_LIT2] = DISP_ENT(L_P_LIT2),
#if defined(OVL_LOAD)
        /* GUARDRAIL: a primitive needs THREE things, not two: the X entry (header), the case body (label),
         * and THIS table slot. With only the first two the word is findable, dispatches to cf=P_LOAD, finds
         * no entry, and the default path reports the word as unknown - measured: `0 LOAD` printed `LOAD?`
         * with LOAD's xt correctly in the dictionary and its label compiled 20 lines away. */
        [P_LOAD] = DISP_ENT(L_P_LOAD),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_LITERAL)
        [P_LITERAL] = DISP_ENT(L_P_LITERAL),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_LOOP)
        [P_LOOP] = DISP_ENT(L_P_LOOP),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_LSHIFT)
        [P_LSHIFT] = DISP_ENT(L_P_LSHIFT),
#endif
#if P54_BINOPS >= 7
        [P_LSHIFT] = DISP_ENT(L_P_LSHIFT),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_LT)
        [P_LT] = DISP_ENT(L_P_LT),
#endif
#if P54_BINOPS >= 9
        [P_LT] = DISP_ENT(L_P_LT),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_MS)
        [P_MS] = DISP_ENT(L_P_MS),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_MUL)
        [P_MUL] = DISP_ENT(L_P_MUL),
#endif
#if P54_BINOPS >= 3
        [P_MUL] = DISP_ENT(L_P_MUL),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_OR)
        [P_OR] = DISP_ENT(L_P_OR),
#endif
#if P54_BINOPS >= 5
        [P_OR] = DISP_ENT(L_P_OR),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_OVER)
        [P_OVER] = DISP_ENT(L_P_OVER),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_PAREN)
        [P_PAREN] = DISP_ENT(L_P_PAREN),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_PAUSE)
        [P_PAUSE] = DISP_ENT(L_P_PAUSE),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_PDOTQ)
        [P_PDOTQ] = DISP_ENT(L_P_PDOTQ),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_LOOP)
        [P_PLOOP] = DISP_ENT(L_P_PLOOP),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_RFROM)
        [P_RFROM] = DISP_ENT(L_P_RFROM),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_ROT)
        [P_ROT] = DISP_ENT(L_P_ROT),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_RSHIFT)
        [P_RSHIFT] = DISP_ENT(L_P_RSHIFT),
#endif
#if P54_BINOPS >= 8
        [P_RSHIFT] = DISP_ENT(L_P_RSHIFT),
#endif
#if defined(BLKPRIM)
        [P_SAVE] = DISP_ENT(L_P_SAVE),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_SEMI)
        [P_SEMI] = DISP_ENT(L_P_SEMI),
#endif
#if defined(P43_TASKS)
        [P_SPAWN] = DISP_ENT(L_P_SPAWN),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_STORE)
        [P_STORE] = DISP_ENT(L_P_STORE),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_SUB)
        [P_SUB] = DISP_ENT(L_P_SUB),
#endif
#if P54_BINOPS >= 2
        [P_SUB] = DISP_ENT(L_P_SUB),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_SWAP)
        [P_SWAP] = DISP_ENT(L_P_SWAP),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_TICK)
        [P_TICK] = DISP_ENT(L_P_TICK),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_TOR)
        [P_TOR] = DISP_ENT(L_P_TOR),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_TYPE)
        [P_TYPE] = DISP_ENT(L_P_TYPE),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_UDIVMOD)
        [P_UDIVMOD] = DISP_ENT(L_P_UDIVMOD),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_ULT)
        [P_ULT] = DISP_ENT(L_P_ULT),
#endif
#if P54_BINOPS >= 10
        [P_ULT] = DISP_ENT(L_P_ULT),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_UNLOOP)
        [P_UNLOOP] = DISP_ENT(L_P_UNLOOP),
#endif
#if defined(BLKPRIM)
        [P_UPDATE] = DISP_ENT(L_P_UPDATE),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_WAKE)
        [P_WAKE] = DISP_ENT(L_P_WAKE),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_WCOMMA)
        [P_WCOMMA] = DISP_ENT(L_P_WCOMMA),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_WFETCH)
        [P_WFETCH] = DISP_ENT(L_P_WFETCH),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_WSTORE)
        [P_WSTORE] = DISP_ENT(L_P_WSTORE),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_XOR)
        [P_XOR] = DISP_ENT(L_P_XOR),
#endif
#if P54_BINOPS >= 6
        [P_XOR] = DISP_ENT(L_P_XOR),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_ZBRANCH)
        [P_ZBRANCH] = DISP_ENT(L_P_ZBRANCH),
#endif
#if !defined(P31_SUBSET) || defined(P_HAVE_ZEQ)
        [P_ZEQ] = DISP_ENT(L_P_ZEQ),
#endif
    };
#undef DISP_ENT
    /* GUARDRAIL: the 11-bit token field carries BOTH forms — an address (even, code field at it) and a
     * primitive id (descending from PRIM_TAG). An address that reached the tag space would decode as some
     * primitive, i.e. dispatch the wrong word with no trace, so the ceiling is asserted HERE, where the id
     * count is known, instead of being left to a comment. */
    _Static_assert((u32)MEMSZ < PRIM_TAG - 2u * (u32)P_COUNT,
                   "a real xt would collide with the primitive tag space");
    for (;;) {
top:
#ifdef P42_COUNT
        p42_dispatches = p42_dispatches + 1u;
#endif
        /* GUARDRAIL: a token is either an ADDRESS (even, its first 2 B are the code field) or a PRIMITIVE ID
         * (odd, 2*id+1). This is the only decode site; EXEC re-enters it through `top`. The bound check
         * below still has to run on the decoded id, because mem[] can hold any halfword. */
        /* GUARDRAIL: `t <= 2*(P_COUNT-1)` is doing TWO jobs, so do not "simplify" it into a plain compare:
         * it is the tag test AND the range bound for the primitive case. A forged ODD token lands on a
         * neighbouring id inside that bound — bounded, not a memory hazard — while an address (much larger
         * than PRIM_TAG - w) falls through to the code-field path.
         * GUARDRAIL: no `& 0xffeu` on w. find() returns the header field with bit 0 (the imm flag) cleared,
         * so every token the dictionary can emit is even; the mask was 2 wasted instructions. */
        u16 t = (u16)(PRIM_TAG - w);
        u16 cf = (t <= (u16)(2u * (u32)(P_COUNT - 1))) ? (u16)(t >> 1) : rd16_paged(w);
        /* P57 GUARDRAIL: dispatch through a 2-byte offset table instead of GCC's switch table. The switch
         * table is 4-byte absolute addresses; label DIFFERENCES are constant enough for a static
         * initializer on this target (measured: .srodata 2 B per entry, `lhu` + `add` + `jalr`).
         * GUARDRAIL: every slot defaults to L_BAD, never to 0 — 0 is a valid offset (it means L_BAD
         * itself), so a zero hole would send a real token down the corrupt-token path.
         * GUARDRAIL: the bound check precedes the dispatch because `cf` comes from mem[] and can be any
         * halfword; without it an out-of-range id indexes past the table. */
        if (cf >= (u16)P_COUNT) { err(); goto tail; }
#ifdef HOST
        goto *disp_tbl[cf];
#else
        goto *(&&L_BAD + disp_tbl[cf]);
#endif
#include "p33_cases.inc"
L_BAD:  err(); goto tail;
tail:
        /* GUARDRAIL: the fault is reported HERE, not inside PUSH, because emitting from an arbitrary
         * primitive can recurse into output while the machine's stacks are unusable. One branch per
         * dispatch buys a named error instead of silent corruption, and the stacks are reset so the REPL
         * survives: the operator loses the line, not the session. */
        if (stack_ovf) {
            /* GUARDRAIL: variant (f) — (d) applied. */
            stack_ovf = 0; sp = 0; rsp = 0; errf_msg(MSG_ERR_STACK);
            VM_FLUSH(); VMD_LEAVE(); return;
        }
#if defined(P43_TASKS)
        if (!ip) { VM_FLUSH(); if (!vm_task_leave()) { VMD_LEAVE(); return; } VM_RELOAD(); continue; }
#else
        /* GUARDRAIL: with tasks off, ip == 0 is simply "return to C". This single call site is what kept the whole
         * scheduler (50 B), vm_next_ready (44 B), vm_switch (62 B), vm_copy (38 B) and the 272 B of task records
         * alive after P43_TASKS went undefined - measured by nm, not by reading the code. */
        if (!ip) { VM_FLUSH(); VMD_LEAVE(); return; }
#endif
        w = rd16_paged(ip); ip += 2;
    }
#undef w
#undef ip
#undef VM_FLUSH
#undef VM_RELOAD
/* restore the file-scope meaning of the two names for everything after vm_enter */
#define w  (V->W)
#define ip (V->IP)
}

#if defined(P54_BINOPS)
/* P54, second half of the subset gate: vm_enter() above consumed src/p54_subset.inc (bodies off), and
 * boot_init() below re-includes p33_prims.inc for the dictionary headers — which read the SAME P_HAVE_*
 * macros. GUARDRAIL: without these redefinitions the ten converted words keep their case removed AND lose
 * their header, i.e. they stop existing: measured `1 2 OR .` -> `OR?` and 54 of 64 dictionary words. It
 * must stay between the two includes, which is why it lives here and not next to p54_ops.h. */
#include "p54_headers.inc"
#endif

/* ---- outer interpreter ---- */
static void interpret(void)
{
    u8 n, imm; u16 xt; u32 v;
    errf = 0;
#if defined(OVL_LOAD)
    /* GUARDRAIL (NOT ENFORCED - see docs/15-overlays.md): a new line arriving while a block still has unread CODE
     * (not just padding) is a silent corruption: the leftover is delivered by a later blk_refill, i.e. in the middle
     * of the next line, and if the machine was left in COMPILE state by a block that ended inside a definition, that
     * line's `N LOAD` is COMPILED instead of executed. Measured on the host trace of a 128 B block: block 9 ended
     * `... NX REPEAT`, the next line's `10` and `LOAD` were read at STATE=1, and the stray `;` arrived afterwards.
     * The check that catches it was written and then withdrawn, because it fires on a legitimate pattern this suite
     * relies on: an intentional refusal (overlay_collide.fs) leaves a partially consumed block whose tail the next
     * line deliberately discards. Enforcing it needs that pattern expressed differently first.
     * THE RULE THAT PREVENTS THE BUG IS TOOL-SIDE and is enforced: tools/fsplit.py cuts blocks only at
     * interpret-state boundaries and refuses a definition that does not fit one block.
     */
#endif
    while (!errf && (n = word())) {
#ifdef P1_TRACE
        if (p1_trace) {                       /* GUARDRAIL: per-token HERE/LATEST is what dates a rewind or a
                                               * silent skip; a dump only at error time cannot see a block that
                                               * quietly never ran. */
            u8 k2;
            fprintf(stderr, "[P1 TOK] ");
            for (k2 = 0; k2 < rd8(PAD); k2++) fputc(rd8(PAD + 1u + k2), stderr);
            fprintf(stderr, "  HERE=%u LATEST=%u ST=%u\n", rd32(V_HERE), rd32(V_LATEST), rd32(V_STATE));
            p1_push();
        }
#endif
        /* GUARDRAIL: try number() FIRST for a numeric token. The old order was find() then number(),
         * so every literal in the source paid a *failed* full scan of the header chain (81 entries)
         * before being recognised as a number — measured at ~28 000 cycles per literal, versus ~1 139
         * for a dispatch. A Forth line is mostly numbers; this is the difference between a REPL that
         * responds and one that crawls. The fallback keeps the old order for everything else, so a word
         * named like a number (`-`) or a number that overflows still resolves exactly as before. */
        u8 c0 = mem[PAD + 1];
        int numeric = (c0 >= '0' && c0 <= '9') || (c0 == '-' && n > 1);
        /* GUARDRAIL: V_STATE is read ONCE per token. rd32() is a bounds-checked function call, and this
         * block called it in every branch — up to three times for one typed token, on the hottest
         * interactive path. The state cannot change between those reads: nothing in this block executes a
         * word (clit/cw/PUSH/run happen after the decision), so the hoist is not just cheap, it is exact. */
        u32 compiling = rd32(V_STATE);
        if (numeric && number(n, &v)) {
            if (compiling) clit(v); else PUSH(v);
        } else if ((xt = find(n, &imm))) {
            if (compiling && !imm) cw(xt); else run(xt);
        } else err();
        /* GUARDRAIL: there used to be a third arm here - `else if (!numeric && number(...))` - kept so a
         * non-numeric token could still parse as a number. With the base fixed at 10 that arm can never be
         * taken: a token that is neither digit-led nor a word cannot parse. It is gone. */
    }
#ifdef P1_TRACE
    /* GUARDRAIL: dumping the state at the END of every source is what dates "a definition was left open here".
     * A rewind does not fire for this case - nothing errored - so the error-time dump cannot see it. */
    if (p1_trace && rd32(V_STATE)) p1_dump("END-COMPILING");
#endif
    if (errf) {
        sp = rsp = 0;
        if (rd32(V_STATE)) { wr32(V_HERE, savehere); wr32(V_LATEST, savelatest); }
        wr32(V_STATE, 0); ti = tl;
#if defined(OVL_LOAD)
        /* GUARDRAIL: an error must also disarm the source switch, or the remains of a half-loaded block would
         * be fed to the NEXT line and compile into whatever the operator typed after the failure. */
        wr32(V_LOADB, 0);
#endif
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
    wr32(V_HERE, DICT); wr32(V_LATEST, HDRTOP); wr32(V_STATE, 0);
    /* GUARDRAIL: the boot assert runs on the zero definition state, i.e. before any dictionary word
     * can be compiled — it is the only moment the pool's *shape* can be judged without a definition
     * having already written past the buffer. The per-transfer check covers the rest. */
#if defined(P33_BLOCK)
    blk_boot_assert();
#endif
#define X(id, name, imm) \
    { const char *s = name; u8 n = 0; while (s[n]) { wr8(PAD + 1 + n, s[n]); n++; } wr8(PAD, n); \
      x = mkhdr_prim(P_##id, imm); \
      (void)x; }
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
/* GUARDRAIL: 16 -> 64 blocks, HOST ONLY (the fake server does not exist on the chip; the main core serves
 * there). tests/overlay_capacity.fs needs ~16 blocks of phase source to prove that a paged program beats the
 * single-image size, and the answering range had to grow with it. The two deliberate failures the other tests
 * depend on are kept by number: block 5 never answers (tests/blocks_noserver.fs), block 7 answers with a bad
 * checksum (tests/blocks.fs). 64 x 128 B of .bss in the host binary, 0 B on the chip. */
#define SRVBLK 64
static u8 srv[SRVBLK][BLKSZ];

static void srv_answer(void)
{
    u32 n = mailbox[0], op = mailbox[1], k, s = 0;
    /* GUARDRAIL: a block the file does not contain must stay *silent*, not nack — the no-answer
     * path is the one that must be measured, and a fake server that always answers cannot show it. */
    /* blocks 0..63 answer except 5 (silent: the no-answer path) and 7 (bad checksum, below) */
    if (n == 5u || n >= (u32)SRVBLK) return;
    if (op == BLK_READ)      for (k = 0; k < BLKSZ; k++) wr8(BLKADR + k, srv[n][k]);
    else if (op == BLK_WRITE) for (k = 0; k < BLKSZ; k++) srv[n][k] = rd8(BLKADR + k);
    for (k = 0; k < BLKSZ; k++) s += srv[n][k];
    mailbox[3] = (n == 7u) ? (s ^ 1u) & 0xffffu : s & 0xffffu;
    mailbox[2] = 1u;                     /* answered: 1 = ok */
}
#endif

int  pl_key(void)        { int c = getchar(); if (c == EOF) exit(0); return c; }
/* GUARDRAIL: the HOST build needs this too, or the bake fails with "undefined reference to pl_keyq" and leaves a STALE
 * src/image.h behind - the build then succeeds against a dictionary for a different MEMSZ. Always provide the hook the
 * engine calls, even when the host's answer is trivial. */
int  pl_keyq(void)       { return 1; }   /* the host reads stdin lazily; there is always "possibly a key" */
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
/* GUARDRAIL: -k (host only, #ifndef IMAGE so the chip pays nothing) keeps loading after an error. It exists
 * because some errors are the ASSERTION: a test that proves a bad overlay is REFUSED still has to show
 * that the resident word survived, and a loader that exits on the first error cannot show the aftermath.
 * It is not a way to make a broken tree look green: the transcript still contains the error line, and the
 * runner compares it byte for byte. */
#ifndef IMAGE
static int keep_going;
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
        if (errf) {
            fprintf(stderr, "%s:%d: error\n", file, ln);
#ifndef IMAGE
            if (keep_going) continue;      /* the error is the assertion; show the aftermath too */
#endif
            return 1;
        }
        if (sp >= SD) {
            fprintf(stderr, "%s:%d: stack underflow\n", file, ln);
#ifndef IMAGE
            if (keep_going) continue;
#endif
            return 1;
        }
    }
    fclose(f);
    return 0;
}

#if defined(P33_BLOCK) && defined(HOST)
/* GUARDRAIL: the host fake server answers a FIXED pattern (k + 7n), so a phase's real bytes could never be
 * replayed on the host - only on the chip, which is expensive and where the diagnostic is one line of text.
 * `-B <file>` reads "<blk> <hex>" lines into the store and pads the remainder with spaces, exactly as the
 * chip's seeder does after the stale-tail fix. Without the padding the host would reproduce a DIFFERENT bug. */
static int p1_load_blocks(const char *path)
{
    FILE *f = fopen(path, "r"); char buf[640], hex[640]; unsigned blk; int k, hexlen;
    if (!f) { fprintf(stderr, "P1: cannot open %s\n", path); return 1; }
    while (fgets(buf, sizeof buf, f)) {
        if (sscanf(buf, "%u %639s", &blk, hex) != 2) continue;
        if (blk >= (unsigned)SRVBLK) { fprintf(stderr, "P1: block %u out of range\n", blk); fclose(f); return 1; }
        hexlen = (int)strlen(hex) / 2;
        for (k = 0; k < hexlen && k < BLKSZ; k++) { unsigned v; sscanf(hex + 2 * k, "%2x", &v); srv[blk][k] = (u8)v; }
        for (; k < BLKSZ; k++) srv[blk][k] = ' ';
    }
    fclose(f); return 0;
}
#endif

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
#ifdef P1_TRACE
    p1_trace = (getenv("ULP_TRACE") != 0);
#endif
#ifdef P31_TRACE
    /* GUARDRAIL: this must be taken between boot_init() and the first load() — after the first file
     * the ceiling moves and layer headers are misread as primitives (P31). */
    p31_prim_here = rd32(V_HERE);
#endif
    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-d") && i + 1 < argc) dump = argv[++i];
#ifndef IMAGE
        else if (!strcmp(argv[i], "-k")) keep_going = 1;
#endif
        else if (!strcmp(argv[i], "-i")) interactive = 1;
#if defined(P33_BLOCK) && defined(HOST)
        /* GUARDRAIL: -B is a TEST capability, not a trace feature. Gating it behind P1_TRACE meant known_defects.sh
         * could not drive a block's real bytes without also compiling the tracer. */
        else if (!strcmp(argv[i], "-B") && i + 1 < argc) { if (p1_load_blocks(argv[++i])) return 1; }
#endif
        else if (load(argv[i])) return 1;
    }
#ifndef IMAGE
    /* GUARDRAIL: step ready tasks on the HOST too. `vm_run_tasks` was called only from the ULP's main, so
     * two-task EXECUTION was never exercised on the host — and a scheduler change that ran only the first
     * of two spawned tasks passed all 12 checks with an identical bench, failing only on the chip (P60).
     * GUARDRAIL: only after a CLEAN load and never during a bake (-d): a file that aborts on errf must not
     * execute half-defined tasks, and a dump must be a pure image of what was compiled.
     * GUARDRAIL: requires a clean stack, exactly as the ULP does — a task switch overwrites vm_live, so a
     * pending value would be silently lost. */
#if defined(P43_TASKS)
    if (!dump && !interactive && vm_next_ready(-1) >= 0 && sp == 0u && rsp == 0u) vm_run_tasks();
#endif
    /* GUARDRAIL: with tasks off there is nothing to step, and the two calls above are the ONLY reason the host driver
     * needed the scheduler - leaving them unconditional is a link error ("undefined reference to vm_next_ready"), which
     * is the good kind of failure but still costs a bake cycle. */
#endif
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
            fprintf(stderr, "image: code %u + headers %u, free %u (MEMSZ %u, "
                            "%u words x %u B)\n",
                    here, (u32)HDRTOP - latest, latest - here, MEMSZ,
                    ((u32)HDRTOP - latest) / HDRSZ, (unsigned)HDRSZ);
        }
        /* GUARDRAIL: a 13-bit hash over this dictionary must be checked when it is BUILT. A collision does
         * not fail a lookup loudly — it returns the wrong word, and the machine has no way to report that.
         * 85 words in 8 192 values is 0.44 expected collisions: a coin flip, which is exactly the odds
         * that are never worth betting when the prize is a silent wrong dispatch (F-107).
         * GUARDRAIL: this check compares the STORED keys pairwise, so it stays correct if hash_pad ever
         * changes; it does not (and cannot) recompute the hash from names, because the image keeps no
         * names. The injectivity search lives in tools/hashsearch.py, on the name list -DP54_NAMES dumps. */
        {
            u32 a, b, ka, kb;
            for (a = rd32(V_LATEST); a + HDRSZ < (u32)HDRTOP; a += HDRSZ) {
                ka = rd24(a) >> 11;
                for (b = a + HDRSZ; b + HDRSZ <= (u32)HDRTOP; b += HDRSZ) {
                    kb = rd24(b) >> 11;
                    if (ka == kb) {
                        fprintf(stderr, "FATAL: hash collision 0x%04x between xt=%u and xt=%u — "
                                "widen the hash or rename a word\n",
                                (unsigned)ka, (unsigned)(rd24(a) & 0x7feu),
                                (unsigned)(rd24(b) & 0x7feu));
                        exit(3);
                    }
                }
            }
        }
    }
    /* GUARDRAIL: bench-only, and gated so it cannot ship: the dispatch count is the ONE number that is
     * identical across hosts (wall-clock is not), which is what makes an acceptance test portable. Printed
     * on the host only — the ULP has no stdout, and this costs bytes there for nothing. */
#if defined(P42_COUNT) && defined(HOST)
    printf("\nDISP %u\n", (unsigned)p42_dispatches);
#endif
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
