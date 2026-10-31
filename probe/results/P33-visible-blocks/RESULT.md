# P33 — Does a visible block layer fit where transparent paging did not?

| | |
| --- | --- |
| Result | **Yes on the pool, and much cheaper than transparency on the dictionary — but the Forth wrapper is not yet proven to execute.** Dropping frames, page table and the paged fetch path from P32's variant D and adding one 512 B buffer plus `BLOCK`/`UPDATE`/`SAVE` **links for real at 7856**: the image is **7 071 B, spare 785 B** (465 B with the C stack honoured inside the pool), against D's 8 656 B / 800 B over. The engine goes **3 916 → 4 096 B** (+180 sections, +198 like-for-like): the transparency removal is **−168 B** and the block layer's own C is **≈ +366 B** — the handshake, the bounded poll, the 512 B checksum and the one `case` body, i.e. above the probe's ~200 B guideline, priced and named in §1.3. **The dictionary is where this shape actually pays:** the whole Forth layer is **456 B of dictionary** (`BLOCK`, `UPDATE`, `SAVE`, `BLK-ABORT`, three named codes, `RAISE`) against P34's transparent wrappers at **888 B** — **432 B cheaper, 49% less**, and that is the operator's productivity-suite number. On the host the protocol is 4/4: read returns the fake server's bytes, `SAVE` writes back to the server's copy, no answer is `ERR_NO_SERVER` with the buffer left intact, and a second request while one is outstanding is `ERR_BUSY`. **The wrapper words themselves hang** (`BLOCK` = `0 BLKXFER` + one `IF…EXIT THEN`) — a defect in this engine's compiled branches (§2.4), unresolved inside the box, so "the layer executes" is **partially met**: protocol yes, wrapper no. |
| Runs on | **host only** — `riscv32-esp-elf-gcc 14.2.0 (esp-14.2.0_20241119)`, IDF v5.4, P29/P31's script (`LENGTH = 7856`), plus host `gcc 11.4.0` for the execution test. Board untouched, no `/dev/ttyACM*` opened. |
| Time box | **overrun, twice.** The first build died inside three minutes on a source edit that closed a comment it had reopened; the second link was clean but silently lost the 256 B `out_ring` line (§2.3). The host execution then cost four debugging rounds on a prelude defect that predates this probe (§2.4). One build of E, one rebuild after the `out_ring` fix, no retries after that. |
| Sources | `src/` is **P32's `src/` copied verbatim** (`cp -r ../P32-audit-budget/src/. src/`, not `src/` — P32 lost its budget to exactly that nesting), then three additions and the `P33_NOPAGE`/`P33_BLOCK` switches: `src/p33_prims.inc` (P31's table + one entry), `src/p33_cases.inc` (P31's bodies + one case), `src/blocks.fs` (the layer), `src/boot16.fs` (a 16-bit-token prelude for the host test), `src/test_proto.fs`. No call site in `vm_enter` was edited: `rd16_paged`/`rd32_paged` are aliased to `rd16`/`rd32` under `-DP33_NOPAGE`. |
| Artifacts | `artifacts/p33_E_real.{elf,map}` + `p33_E_real_size.txt` (the 7856 B link), `artifacts/p33_E_diag.{elf,map}`, `artifacts/p33_E_nm.txt`, `artifacts/p33_control.elf`, `artifacts/host_blocks` (host binary), `artifacts/mem_dump.h` (dictionary watermark), `logs/p33_E.log`, `logs/host_run.log`, `logs/host_build.log` |

## Record

| Item | Value |
| --- | --- |
| engine after removing frames/table/fetch path | **not separable from the layer by measurement** — the two switches are applied in one build, so the build gives the *net*: 4 096 B (3 868 `.text` + 228 `.rodata`), `.bin − control` 4 110. P32 priced the removal at **−168 B** (`pg_load` 108 + `rd16_paged` 60; both are 0 B in E's `nm`), so the pre-layer engine is **≈ 3 928 B**, i.e. D minus the transparency it no longer needs |
| engine after adding the visible layer | **4 096 B** sections / **4 110 B** `.bin − control`; **+180 B** over D (3 916), **+198** like-for-like once the 18 B the harness gained is removed (§1.3) |
| buffer cost | **512 B of pool**, `mem` 908 → **1 420**; the buffer is `mem[MEMSZ-512]`, so the dictionary keeps its 852 usable bytes and the engine pays **0 B** for it |
| region need vs 7856 | **7 071 B** (`.text` 4 082 + `.rodata` 228 + `.srodata` 8 + `.data` 4 + `.bss` 2 749) — **link OK** |
| **spare** (and with the C stack reserved) | **785 B** (7 856 − 7 071); **465 B** with the C stack honoured inside the pool (7 536 − 7 071) |
| dictionary cost of the layer's Forth | **456 B** — measured, not counted: the prelude alone occupies 888 of 1 420 (`-d`, `image: 888 bytes`), prelude + `blocks.fs` occupies 1 344 (`image: 1 344 bytes`), so `blocks.fs` = **456 B** for `BLOCK`, `UPDATE`, `SAVE`, `BLK-ABORT`, `ERR_BUSY`/`ERR_NO_SERVER`/`ERR_CRC` and `RAISE` |
| host execution | `BLOCK` (read) **PASS** at the protocol level, wrapper **FAIL** (hang); `UPDATE`+`SAVE` (write back) **PASS** protocol, wrapper **FAIL** (hang); `ERR_NO_SERVER` **PASS**; `ERR_BUSY` **PASS**; plus `BLK-ABORT` **PASS** and `ERR_CRC` **PASS** |

## 1. Answers

### 1.1 What "no transparency" actually buys

P32 priced transparency at **2 466 B** — `frm` 2 048 + `ptab` 16 + `ptab_lru_reserve` 234 in the pool,
`pg_load` 108 + `rd16_paged` 60 in the engine. Every one of those bytes exists so that `@` and `!` can
touch an address the machine has not got. A visible block layer does not want that property, so the
removal is total and unconditional (`-DP33_NOPAGE`), with the call sites left alone:

```c
#if defined(P33_NOPAGE)
#define rd16_paged(a) rd16(a)
#define rd32_paged(a) rd32(a)
#else
   ... frames, page table, pg_load, resolve, rd16_paged, rd32_paged (unchanged) ...
#endif
```

`nm -S` on E confirms the removal rather than assuming it: `frm` **absent**, `ptab` **absent**,
`ptab_lru_reserve` **absent**, `pg_load` **0 B**, `rd16_paged` **0 B**. The `FAULT`/retry state machine
goes with them — `vm_faults_left`/`vm_sw_fault` are still in the source but nothing in the fetch path
increments them any more, so there is no fault to resume from.

### 1.2 What the visible layer costs, and where

| Part | Bytes | Where |
| --- | --- | --- |
| one 512 B buffer, `BLKADR = MEMSZ - BLKSZ` | **+512** | pool (`.bss`, inside `mem`) |
| `blk_out` (the single-outstanding flag) | +4 | pool (`.bss`) |
| the C layer: `blk_xfer` + `blk_sum` + the `BLKXFER` case + its name string | **≈ +366** | engine (`.text` + `.rodata`) |
| the Forth layer: `BLOCK`, `UPDATE`, `SAVE`, `BLK-ABORT`, 3 codes, `RAISE` | **456** | dictionary (`mem`), 0 B of engine |
| *removed*: frames 2 048 + table 250 + fetch path 168 | **−2 466** | pool −2 298, engine −168 |
| **net against D's 8 656 B** | **−1 585** | → 7 071 B |

The buffer is inside `mem[]` on purpose: `C@`/`!` address `mem[]` by offset, so a separate
`static u8 blkbuf[512]` would be 512 B that **no Forth word can reach** — a budget line that cannot be
a block buffer (P34 paid that differently and had to add `F@`/`F!` to reach it).

### 1.3 The engine delta, and why it is bigger than the probe expected

| Build | sections | `.bin − control` | control `.text` |
| --- | --- | --- | --- |
| D (P32) | 3 916 (3 720 + 196) | 3 928 | 196 |
| **E (P33)** | **4 096 (3 868 + 228)** | **4 110** | **214** |

P33's control is 18 B larger than P32's because the touch list in `ulp_stubs.c` gained one line that
*reads* `out_ring` (§2.3). Like-for-like against P32's convention, E is `4 324 − 196 = **4 128**`, i.e.
**+200 B** over D. Take out the −168 B of transparency and the visible layer's own C is **≈ +366 B**:

| symbol | D | E | Δ | what it is |
| --- | --- | --- | --- | --- |
| `vm_enter` | 1 794 | **1 964** | **+170** | `blk_xfer` inlined at its one call site, minus the inlined `pg_load`/`resolve`/`rd16_paged` |
| `blk_sum` | 0 | **50** | **+50** | the 512 B checksum, kept out of line because two paths call it |
| `.rodata` | 196 | **228** | **+32** | the `BLKXFER` name string + the constants the poll needs |
| `word`/`find`/`mkhdr` | 202/148/148 | 202/148/148 | 0 | the outer interpreter did not reshuffle this time |

This is **above the probe's ~200 B guideline** and it is worth saying plainly what the extra buys:
a bounded poll over a `volatile` status word, a checksum over the whole buffer in both directions, a
single-outstanding guard, and the mailbox protocol (request, doorbell, status, checksum) — the part of a
block file that is *machine*, not Forth. A layer cheap enough to be 200 B would be a layer that cannot
tell a corrupt page from a good one.

### 1.4 What R5 becomes

**R5 becomes a 2 KB visible block file: `BLOCK n` refills one 512 B buffer and hands back its address,
`UPDATE`/`SAVE` send it back, exactly one request may be outstanding, the wait is bounded and every
failure is named — storage you ask for by name, costing 512 B of pool and 456 B of dictionary, with no
`@`/`!` on storage, no page table and no fault path.**

## 2. Evidence

### 2.1 The 7856 B link is a link result, not arithmetic

```sh
tmux new-session -d -s p33 './run.sh E 1420'      # timeout 300 nice -n 10 python3 p33_build.py E 1420
grep -E "variant E|region use|arrays" logs/p33_E.log
riscv32-esp-elf-size -A artifacts/p33_E_real.elf      # -> artifacts/p33_E_real_size.txt
```

```
variant E: text=3868 rodata=228 engine(.bin - control)=4110 real-7856-link=OK
E arrays: frm=None ptab=None ptab_lru_reserve=None cmd_ring=128 out_ring=256 mailbox=216
          tib=128 mem=1420 vm_live=136 tsk=420 blk_out=4 MISSING=frm,ptab,ptab_lru_reserve
.text 4082  .rodata 228  .srodata.seed.0 8  .data 4  .bss 2749   -> 7071 of 7856
```

`mem` 1 420 = 908 dictionary + 512 buffer; `tsk` 420, `tib` 128, `mailbox` 216, `cmd_ring` 128,
`out_ring` 256, `vm_live` 136 are all present at D's sizes, so the three `MISSING` symbols are the only
thing that left the image.

### 2.2 The layer's dictionary cost, measured

```sh
./artifacts/host_blocks -d artifacts/mem_dump.h src/boot16.fs                 # image: 888 bytes of 1420
./artifacts/host_blocks -d artifacts/mem_dump.h src/boot16.fs src/blocks.fs   # image: 1344 bytes of 1420
```

`1344 − 888 = **456 B**` is the Forth side of `BLOCK`/`UPDATE`/`SAVE`/`BLK-ABORT`. The 888 B is the
fixture (primitive headers ≈ 640 B from `boot_init` + a 248 B prelude) and is *not* the layer's cost —
it stands in for the P26 prelude already inside `mem` 908. Against P34's transparent wrappers
(**888 B**, 636 headerless), the explicit layer is **432 B cheaper and 49% smaller**, and both charge
the same 512 B buffer to the pool. That is the decision the suite needs: the explicit shape buys back
~430 B of the 1 008 B app space P34 could not fit.

### 2.3 A budget line that vanished, caught by `nm`

The first E link reported `out_ring=None`. With `frm` gone, the only *reader* of `out_ring` in D's image
was the touch line `*(volatile u8 *)&frm[0][0] = out_ring[…]`; removing it left `pl_emit`'s store
dead, GCC deleted it, and the whole 256 B ring line left the image:

```
pl_emit:  lw a4,-1496(a5)   # ring_head
          lw a4,-1496(a5)
          addi a4,a4,1
          sw a4,-1496(a5)   # ring_head++   -- no store to out_ring at all
```

That is P22's 192 B lesson in the opposite direction: a budget line can disappear when the probe removes
the code that *reads* it. Fixed by reading `out_ring` in the touch list (`ulp_stubs.c`), which is what
moved the control's `.text` from 196 to 214.

### 2.4 Host execution — the protocol passes, the wrapper does not

```sh
./host.sh                                                  # gcc -O1 -DHOST -DP33_NOPAGE -DP33_BLOCK
./artifacts/host_blocks src/boot16.fs src/test_proto.fs
```

```
read-blk0    PASS     blk0[3]=3    PASS     blk0[200]  PASS
read-blk2    PASS     blk2[100]   PASS
save-blk0    PASS     reread-blk0 PASS          (server prints SRV blk0[9]=2a)
no-server    PASS     no-zero-fill PASS         (-3, buffer still holds 42)
busy         PASS                                (-2, the unanswered request is still out)
abort+read   PASS     reread-ok   PASS          (BLK-ABORT clears, block 0 reads back 42)
crc          PASS                                (-4)
```

Both write-back proofs are on the *server's* side: the fake file's `blk0[9]` becomes `2a` only because
`BLKXFER` sent the buffer, and the re-read passes only because the server's copy now holds it. The
no-answer case leaves the buffer with its previous bytes — no zero-fill — and the following request is
refused `ERR_BUSY` rather than racing the stale answer.

**The wrapper does not execute.** `src/blocks.fs` loads and compiles (no error), but the first call to
`BLOCK` — a `DUP BLKN !`, one `0 BLKXFER`, and a single `IF … EXIT THEN` — hangs. Reduced to a
10-line file, the hang reproduces as *any* `IF … THEN` whose body stores to a `CREATE`-allocated cell
(`: B7 0= IF 0 BLKDRT ! 75 EMIT THEN ; 0 B7`), while `0 BLKDRT !` outside a branch, `66 EMIT` inside a
branch, and `0 BLKN !`/`0 BLKERR !` inside a branch all run. Two things were established on the way:

* **`boot_min.fs` is P02-era and wrong for this engine.** Its `IF` emits a 4-byte branch operand
  (`0 ,` + `HERE 4 -`) while `ZBRANCH` reads 2 bytes and skips 2 — a compiled `IF` branches two bytes
  past the truth and *hangs*, not errors. `src/boot16.fs` is the 2-byte version (`0 W,`, `HERE 2 -`),
  and every result above is from it.
* The residual wrapper hang is **not diagnosed**. It is not the store address (writing `BLKDRT` and
  looking it up again works), not the branch itself (a branch body that emits works), and not the code
  generation of the layer (it compiles clean). Until it is explained, the layer's Forth is unproven
  and no claim should rest on it.

## 3. Verdict

**The pool is not the obstacle any more: a visible block layer fits at 7 071 of 7 856 — 785 B spare,
465 B with the C stack reserved — where transparent paging was 800 B over.** On the probe's criteria:

* *the machine links with the language, three tasks, the console and the visible block layer* —
  **met**: the real 7856 B link succeeds, `I J UNLOOP GPIO! ' CONSTANT ( ."` are all still there, `tsk`
  420 (`NTSK=3`), `tib` 128, `mem` 1 420, and only `frm`/`ptab`/`ptab_lru_reserve` left the image.
* *the layer executes on the host: read, write back, and both named failures* — **partially met**: the
  protocol is 4/4 (§2.4, server-side write-back proof, no zero-fill, `ERR_BUSY` honoured), but the
  Forth wrapper `BLOCK`/`UPDATE`/`SAVE` hangs on this engine's compiled branches and is not proven.
* *the spare stated as a number, both ways* — **met**: 785 B / 465 B.

The plain statement: **transparency was 2 466 B; the visible interface is 512 B of buffer, ~366 B of
engine and 456 B of dictionary — a quarter of the price for the storage and none of the transparency.**
The engine cost is above the probe's ~200 B guideline and the ~366 B is *named* (§1.3): a bounded poll,
a checksum, a single-outstanding guard and the mailbox protocol. The dictionary cost is the number that
matters for the suite: **456 B against P34's 888 B** — so if storage is wanted in the 1 008 B app space,
the explicit shape is the one that can have it. **Recommendation to the operator: keep R5, in the visible
shape — conditional on the wrapper defect in §2.4 being explained before any Forth rests on it.**

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §4.4 — the visible-block variant, its cost and its spare

```
**The block layer, visible (P33).** Transparent paging is not in v1. It cost 2466 B (frames 2048 +
table 250 + paged fetch path 168) plus a fault/retry machine, and with the language restored the
machine was 800 B over the pool. What it buys is *transparency* — `@`/`!` reaching an address the
machine has not got — and a programmer's block file does not want that. So storage is visible:

| Item | Bytes | Artifact |
| --- | --- | --- |
| one 512 B block buffer, `mem[MEMSZ-512]` | **512** | `mem` 908 -> 1420 (`.bss`) |
| single-outstanding flag | 4 | `blk_out` |
| C layer: bounded request/wait/checksum/one primitive `BLKXFER` | **~366** | `vm_enter` +170, `blk_sum` 50, `.rodata` +32 |
| Forth layer: `BLOCK` `UPDATE` `SAVE` `BLK-ABORT` + `ERR_BUSY` `ERR_NO_SERVER` `ERR_CRC` | **456** | dictionary (`mem`), 0 B engine |
| *removed*: frames 2048, table 250, fetch path 168 | **-2466** | pool -2298, engine -168 |

Engine 4096 B (3868 `.text` + 228 `.rodata`); image **7071 of 7856 = 785 B spare**, or **465 B** if the
320 B C stack is honoured inside the pool. Exactly one request may be outstanding (P16: two corrupt
silently with a valid CRC), the wait is a counted loop (~10x P16's 2740-cycle fetch), and every failure
is a named code: `ERR_BUSY` -2, `ERR_NO_SERVER` -3, `ERR_CRC` -4. A failed `BLOCK` returns its code and
leaves the buffer untouched — it never returns a zero-filled buffer.
```

### 4.2 `docs/01-proposal.md` §7 — the R5 wording

```
**R5 — block storage, visible.** A 2 KB file of four 512 B blocks. `BLOCK ( n -- addr )` refills one
buffer and returns its address; `UPDATE` marks it; `SAVE` sends it back; `BLK-ABORT` drops a request
that was never answered. One request in flight, ever; a bounded wait; named failures. No page table, no
frame residency, no fault path, and therefore no `@`/`!` on storage: a word that wants block 3 says so,
exactly as the 1980s block file did. Cost: 512 B of pool and 456 B of dictionary, against 2466 B for the
transparent version P32 could not fit — and 456 B is 432 B less than the Forth shadow words that would
have hidden it (P34, 888 B).
```

### 4.3 `docs/JOURNAL.md` — the decision and what R5 became

```
**Transparency was the expensive half, so it is the half we dropped.** P32 left the choice of how to
close 800 B over the pool. P33 built the alternative rather than arguing it: P32's variant D with the
frames, the page table and the paged fetch path removed (-DP33_NOPAGE, call sites untouched, `nm`
confirming `frm`/`ptab`/`ptab_lru_reserve`/`pg_load`/`rd16_paged` all gone) and one 512 B buffer plus
`BLOCK`/`UPDATE`/`SAVE` added. It links for real at 7856: **7071 B, 785 B spare (465 B with the C stack
reserved)**, engine 3916 -> 4096 B. The C side is one primitive, `BLKXFER`, ~366 B: request, doorbell,
bounded poll over a volatile status, 512 B checksum, single-outstanding guard. Everything an operator
sees is Forth, and it is **456 B of dictionary** — 432 B less than the `@`/`!` shadow words of P34's
transparent version (888 B), which is the difference between storage fitting the 1008 B app space and
not fitting it. On the host the protocol is 4/4 (read, write back to the server's own copy, ERR_NO_SERVER
with the buffer intact, ERR_BUSY on a second request); the Forth wrapper hangs on this engine's compiled
branches and must be explained before the layer is trusted. R5 survives in its visible form.
```

### 4.4 `docs/06-repl.md` — no change to the console

```
The console gains no block command in v1: `BLOCK n` prints nothing and returns an address, and the
layer's only reportable state is `BLKERR`. If a listing is wanted later it is `BLOCKS` in Forth
(456 B + ~40 B), not a C word.
```

## 5. Follow-ups

1. **Explain the wrapper hang before anything rests on `blocks.fs`** (§2.4). It reproduces in ten lines
   and it is in the *engine*, not the layer: a branch whose body stores to a `CREATE`-allocated cell.
   Until then the layer is a design with a proven protocol and an unproven surface.
2. **`boot_min.fs` is wrong for the 16-bit engine, and three probes' host tests load it** (P10's REPL
   host, P26's layer tests, P31's host builds). Its `IF` writes a 4-byte branch operand that `ZBRANCH`
   reads as 2 — the symptom is a hang, not an error. `src/boot16.fs` is the 2-byte version; it belongs
   in `probe/` so the next host test does not rediscover it.
3. **Check every budget line with `nm` after removing anything.** §2.3: `out_ring` 256 B vanished because
   the removed `frm` touch was its only reader, and the first link looked 256 B better than it was.
4. **The C layer is ~366 B, not ~200.** If that is too much, the checksum is the first candidate (50 B
   plus its call sites) — but then `ERR_CRC` disappears and P16's corruption mode becomes silent again.
   The second candidate is the poll: `BLKWAIT` 4 096 could be derived from a cycle count instead.
5. **`-Oz` not tried** (P31's follow-up 4, still open). E is exactly the shape it optimises.
6. **One stray write outside the probe directory**: a scratch file was created at `/tmp/x.fs` while
   debugging the prelude and never used. Nothing else was written outside `probe/results/P33-visible-blocks/`.
