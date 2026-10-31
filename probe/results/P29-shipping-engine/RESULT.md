# P29 — The shipping engine: does it still fit with the switch in it?

| | |
| --- | --- |
| Result | **FAIL — the 232 B is gone, and by 1836 B, not by 232.** The engine links at `MEMSZ` 908 only in a diagnostic region; at the real 7856 B pool the link stops with `address 0x25dc ... section '.bss' is not within region 'ram'` — **1836 B over**. The engine is **`.text` 4670 + `.rodata` 264 = 4934 B**, **+1744 B against P22's 3190** (`.bin − control` 4948, +1750). The overrun is **not** the switch: `vm_switch` is 102 B, the fault path reuses it, and neither stack copy was inlined twice. It is the **dispatch loop** — `vm_enter` is **2380 B**, 51 % of the engine — plus **400 B of libgcc** (`memcpy` 232, `memset` 168) that `tsk[from].vm = *V` and `vm_task_init`'s zero loop pull in, code that did not exist before the switch. Allocation is confirmed by symbol for every budget array (`frm` 2048, `ptab` 16, `ptab_lru_reserve` 234, `cmd_ring` 128, `out_ring` 256, `mailbox` 216, `tib` 128, `mem` 908, `vm_live` 136, `tsk` 420) — the stacks are 128 B *inside* `vm_live`, so they are present under another name and are checked as such. Nothing was trimmed. The dictionary side is unchanged and still fits: `MEMSZ` 908 vs resident need 676 = **+232**, which is now irrelevant because the pool is 1836 B short before the dictionary is asked for anything. |
| Runs on | **host only** (compile + link with IDF's own generated rv32imc flags). Board untouched, no `/dev/ttyACM*` opened. |
| Target / toolchain | `esp32s3` ULP-RISC-V, `riscv32-esp-elf-gcc 14.2.0 (esp-14.2.0_20241119)`, ESP-IDF v5.4, `-Os -march=rv32imc_zicsr_zifencei -mdiv -fdata-sections -ffunction-sections`, P22's linker script (`LENGTH = 7856`) |
| Sources | `src/uforth.c` = **P27's `uforth.c` verbatim as the base** (16-bit xts, 32-bit data cells, `VM`/`vm_switch`/records/fault path) **+ P22's paging, frames/page table and budget arrays folded in**, every token fetch routed through `rd16_paged()`; `src/ulp_stubs.c` = the layer's four hooks as real code (`pl_key`, `pl_emit` → `out_ring`, `pl_hw` → `mailbox`, `pl_halt` → latch, called from `vm_task_leave`) + `main`; `p29_build.py`/`run.sh` = P22's recipe, parameterised by `MEMSZ`; `src/ulp_p29.ld` = P22's script; `src/ulp_p29_diag.ld` = same script with `LENGTH = 12000`, **diagnostic only**, used to place an over-budget image so `nm -S` can be read |
| Time box | **overrun: ~15 min of work in ~35 min.** Cost of the overrun: the P26-layer-included link (§2.4) and a control-subtracted symbol split of P22's own inner loop were not run. Neither changes the verdict — the engine alone already fails by 1836 B |

## Record

| Item | Value |
| --- | --- |
| engine `.text` / `.rodata` / total | **4670 / 264 / 4934** (`.bin − control` = **4948**; raw sections `.text` 4866, `.rodata` 264, `.srodata` 8, `.data` 4; control `.text` 196) |
| delta vs P22's 3190 | **+1744** (`.text` **+1660**, `.rodata` **+84**), or +1750 by `.bin − control` |
| `vm_switch` + hooks + 16-bit fetch, bytes | `vm_switch` **102**, `vm_task_leave` 76, `vm_next_ready` 52 ⇒ switch trio **230**; hooks **196** total, subtracted as the control image (`pl_emit` 34 + `pl_halt` 46 are symbols, `pl_hw` 106 and `pl_key` 4 are inlined into `vm_enter`); 16-bit paged fetch `rd16_paged` **60** + `pg_load` 108 (`resolve` inlined into 5 callers, priced inside `vm_enter`); libgcc pulled in by the struct copy: `memcpy` **232**, `memset` **168** |
| allocation confirmed by `nm -S` | **yes** — `frm` 0x800 = 2048, `ptab` 0x10 = 16, `ptab_lru_reserve` 0xea = 234, `cmd_ring` 0x80 = 128, `out_ring` 0x100 = 256, `mailbox` 0xd8 = 216, `tib` 0x80 = 128, `mem` 0x38c = 908, `vm_live` 0x88 = 136 (= DS 64 + RS 64 + sp/rsp/w/ip 8), `tsk` 0x1a4 = 420 (3 × 140). Stacks are VM fields, not symbols — checked, not assumed (§2.3) |
| `MEMSZ` at 3 tasks | **908** (1188 − 3 × 140 + 140, P28's row D) |
| resident need | **676** (P28's measured walk: 636 dictionary + 40 layer data) — **fits `mem[]` with 232 B spare** |
| **final gap** | **−1836 B at the pool level** (region need 9692 vs 7856); the dictionary's +232 B never gets a vote |

---

## 1. Answers

**Q: Does the engine still link at `MEMSZ` 908 with three tasks and the four hooks?**
**No.** Exact message, first attempt, no trimming:

```
ld: address 0x25dc of .../P29-shipping-engine/artifacts/ulp_main_p29.elf
    section '.bss' is not within region 'ram'
collect2: error: ld returned 1 exit status
```

`0x25dc` = 9692, the region ends at 7856 ⇒ **1836 B over**. The failure is not marginal and it is not
about the dictionary: the sections that must be placed are `.text` 4866 + `.rodata` 264 + `.srodata` 8 +
`.data` 4 + `.bss` 4548, and `.bss` alone is 4548 B of which `mem[]` is only 908.

**Q: Where did the 232 B go?**
It was never the number at risk. **The engine grew by 1744 B against P22's 3190** (`.text` 3010 → 4670,
`.rodata` 180 → 264). The 232 B margin was a *dictionary* margin — P28 compared `MEMSZ` available (908)
with resident dictionary need (676). The engine is charged to the *pool* (7856), not to `MEMSZ`, so a
+1744 B engine eats the 232 B and 1512 B more.

| line | B | where it comes from |
| --- | --- | --- |
| `vm_enter` | **2380** | the whole dispatch loop: 61 primitives (P27's set, not P22's 40), the `PAUSE` and `FAULT` cases, and the inlined paged fetch (`resolve`/`pg_load` are inlined at every fetch) |
| `memcpy` (libgcc) | **232** | `tsk[from].vm = *V` — the struct copy P27 calls "the whole switch point" is a 136 B `memcpy` on rv32imc at `-Os`, and the compiler emits a *call*, not 17 inline word moves |
| `memset` (libgcc) | **168** | `vm_task_init`'s `for (j = 0; j < SD; j++) {...= 0;}` is recognised as a memset and becomes a call |
| `vm_switch` | 102 | save/restore selector; **one** struct copy site, no inlined stack copy (the failure criterion did not fire) |
| `vm_task_leave` + `vm_next_ready` | 128 | retire + round-robin scan |
| `word` + `find` + `mkhdr` + `err` + `clit` | 622 | outer interpreter, present in P22 too |
| `pg_load` + `rd16_paged` | 168 | paging, present in P22 too (but P22 fetched 32-bit cells with one `rd32_paged`) |
| hooks (`pl_*`) | 196 | charged as harness and subtracted (`pl_hw`/`pl_key` inlined, so they sit *inside* `vm_enter`) |
| **engine total** | **4934** | 4670 + 264 |

The three candidates the brief listed are, measured: (1) *`vm_switch` inlining both stack copies* —
**no**, `vm_switch` is 102 B and there is one copy site; (2) *the fault path duplicating the switch* —
**no**, `P_FAULT` calls `vm_switch`; (3) *the 16-bit fetch path adding a sign/mask step* — **partly**,
`rd16_paged` 60 B plus inlined `resolve` in `vm_enter`; (4) *the hooks pulling in ring machinery* —
**no**, 200 B total and subtracted. The real cause is not on that list: **the switch's struct copy pulls
in 400 B of libgcc**, and the 61-primitive dispatch loop that P22 never had in a 16-bit build is 2380 B.

**Q: Is the allocation real this time?**
**Yes, per symbol, and one array needed care.** `nm -S` on the diagnostic link:

```
00001a18 00000800 b frm               2048   frames, 4 x 512
00001a08 00000010 b ptab                16   page table, 4 entries
000016c4 000000ea b ptab_lru_reserve   234   4.3 "page table + LRU" remainder
00001988 00000080 b cmd_ring           128   P04 command ring
00001888 00000100 b out_ring           256   P04 output ring (pl_emit's target)
000017b0 000000d8 b mailbox            216   P04 status mailbox (pl_hw's target)
000015bc 00000080 b tib                128   line buffer (TIBSZ=128)
00002218 0000038c b mem                908   MEMSZ 908, exactly
0000163c 00000088 b vm_live            136   VM: DS[16] 64 + RS[16] 64 + sp/rsp/w/ip 8
00001418 000001a4 b tsk                420   three 140 B records
```

**`ds` and `rs` are absent by design, not by elimination:** P27 moved both stacks into the `VM` struct, so
they are 64 B + 64 B *inside* `vm_live` (136 B) and inside each of the three `tsk` records (140 B each).
A naive `grep ' ds$'` on the ELF returns nothing and would look like P22's 728 B dead-store bug; the check
is `vm_live` = 128 + 8 = 136, which is exact. `pl_halt` is a real hook with a real call site
(`vm_task_leave`, last-task path) and 46 B of its own (`pl_hw`'s 106 B are inlined into `vm_enter`, which is
why it has no symbol of its own).

**Q: What is the final gap, then?**
Two gaps, and they must not be confused:

* **dictionary at 3 tasks:** `MEMSZ` available **908** vs resident need **676** ⇒ **+232 B** (P28's row D,
  unchanged — and `mem` is 908 B in the ELF, so the pool is really there).
* **the pool:** **7856** available vs **9692** needed ⇒ **−1836 B**. The engine is 4934 B, and
  `7856 − 4934 − 2048(frames) − 250(table/LRU) − 128(stacks inside vm_live already counted) − 600(rings+mailbox)
  − 420(records) − 150(VM state) − 128(line buffer) − 908(mem) < 0` before the first dictionary byte.

**Q: Could a smaller `MEMSZ` rescue it?** **No.** `MEMSZ` 0 removes 908 B and the link is still 918 B over.
The overrun is 2× the dictionary.

**Q: Did the engine `-Os` blow up because the paging was bolted onto P27 rather than the other way?**
Probably, and it is measurable in one direction only here: `vm_enter` at 2380 B is 51 % of the engine, and
P22's whole `run()` (unpaged, 40 primitives, 32-bit tokens) fitted inside a 3010 B engine. The 61-primitive
set is P27's `a16` lineage (§2.2), not the shipping set — see §5.1, which is the cheapest place to look for
the missing ~900 B.

---

## 2. Evidence

### 2.1 Commands (all under `timeout`, all outputs inside this directory)

```sh
cp ../P27-resumable/uforth.c          src/uforth.c        # base: 16-bit xts + VM + vm_switch + fault
cp ../P22-fits/src/ulp_p22.ld         src/ulp_p29.ld      # LENGTH = 7856 (8176 - 320 C stack)
cp ../P22-fits/p22_build.py           p29_build.py        # same flags, harness = -DP29_HARNESS_ONLY

timeout 300 nice -n 10 python3 p29_build.py 908   # -> LINK FAILED rc=1, 1836 B over   (logs/p29_build.log)
timeout 300 nice -n 10 python3 p29_diag.py  908   # -> places everything at LENGTH=12000 (logs/p29_diag.log)
timeout 20 riscv32-esp-elf-size -A artifacts/ulp_main_p29_diag.elf
timeout 20 riscv32-esp-elf-nm --size-sort -S artifacts/ulp_main_p29_diag.elf
timeout 20 riscv32-esp-elf-nm -S artifacts/ulp_main_p29_diag.elf | grep -E " (frm|ptab|ds|rs|cmd_ring|out_ring|mailbox|ptab_lru_reserve|tsk|vm_live|tib|mem)$"
```

### 2.2 The edits that make this the shipping engine and not P27

* paging added exactly as P22 has it: `NFRM 4`, `FRMB 512`, `frm[4][512]`, `ptab[4]`, `pg_load()`,
  `resolve()`, `rd16_paged()`, `rd32_paged()`;
* every instruction-stream read moved to the paged form — `vm_enter`'s token fetch, `P_LIT`, `P_BRANCH`,
  `P_ZBRANCH`, the loop-branch tail, `PAUSE`'s pre-save fetch and the dispatch tail. **Four** `rd16(ip/w)`
  call sites existed; all four are `rd16_paged()` now, which is what makes the frames and the table
  reachable and therefore present in `.bss`;
* budget arrays `cmd_ring[128]`, `out_ring[256]`, `mailbox[54]`, `ptab_lru_reserve[234]` declared and kept
  alive through `volatile` stores in `main`;
* `pl_halt()` added as the fourth hook and **called**: `vm_task_leave` latches it when the last task retires;
* `-DSD=16 -DTIBSZ=128 -DNTSK=3 -DMEMSZ=908`;
* `P27`'s `VM` layout is untouched — `u16 W, IP` is what makes 16-bit xts work with 32-bit data cells.

### 2.3 What "confirmed by `nm -S`" means here, per array

| budget line | symbol | `nm -S` | present |
| --- | --- | --- | --- |
| frames 4 × 512 | `frm` | 0x800 = 2048 | **yes** |
| page table | `ptab` | 0x10 = 16 | **yes** |
| page table + LRU | `ptab_lru_reserve` | 0xea = 234 | **yes** |
| command ring | `cmd_ring` | 0x80 = 128 | **yes** |
| output ring | `out_ring` | 0x100 = 256 | **yes** |
| mailbox | `mailbox` | 0xd8 = 216 | **yes** |
| line buffer | `tib` | 0x80 = 128 | **yes** |
| dictionary pool | `mem` | 0x38c = 908 | **yes** |
| data/return stacks (2 × 64) | inside `vm_live` | 0x88 = 136 = 64+64+8 | **yes, as a VM field** |
| 3 × 140 B task records | `tsk` | 0x1a4 = 420 | **yes** |

No line is missing. The link is not a lie; it is simply too big.

### 2.4 What was not run, and the exact size of that hole

* **The layer-included link (method step 2, second half).** There is no 16-bit image of the prelude+layer:
  P26's 1024 B layer was compiled on the **32-bit** engine (P24's lineage), and recompiling it on this
  engine is a port, not a build. It does not change the verdict — the engine alone is 1836 B over, so a
  1024 B layer resident cannot be reached by any “it links” argument. At 16-bit the layer would be ~600 B
  by P28's 1.72× body ratio, still 1836 B too many.
* **A symbol-level split of P22's own inner loop.** P22 reported `.text` 3010 total and no `nm --size-sort`
  table; so the +1660 B `.text` delta is attributed to P29's symbols, and the P22 side of each comparison
  is the section total. Stated so nobody reads `vm_enter` 2380 as “+2380”.
* **The 40-primitive P22 set on this engine.** §5.1's first experiment, and the only one worth running
  before §4.3 changes again.

---

## 3. Verdict

**FAIL, on the probe's own criteria.**

* *the engine links with the switch, the hooks and 16-bit tokens at `MEMSZ` 908* — **does not fire.**
  `MEMSZ` 908 is met (the `mem` symbol is 908 B) but the pool is 1836 B short; `MEMSZ` is not the binding
  constraint and setting it to 0 leaves 918 B over.
* *allocation confirmed by symbol, not by "it linked"* — **met**, §2.3, all ten arrays.
* *the delta against P22 attributed to named symbols* — **met**, §1's table.

The named overrun: **`vm_enter` 2380 B** (51 % of the engine) and **400 B of libgcc** pulled in by the
switch's struct copy (`memcpy` 232) and `vm_task_init` (`memset` 168). Do not trim anything to fit: the
frames, the page table, the rings, `SD=16`, `TIBSZ=128`, the three records and the four hooks are all
present and all charged.

**What this changes:** §4.3 cannot be written with `MEMSZ = 908` and a 3-task verdict. The measured
position is “the shipping engine is 4934 B and the pool is 7856, so the engine plus every fixed line
leaves nothing for the dictionary at all.” The three shapes that follow from the numbers, in order of
cost:

1. **P22's primitive set, not P27's 61.** The dispatch loop is the overrun, and 21 extra primitives plus
   the literal/string/bracket words they bring are inside it. This is a build, not a guess (§5.1).
2. **Two tasks** saves 140 B of records. Not enough on its own — 1836 B is 13 records.
3. **Paging the engine itself** is not available: the frames already exist, but the *code* is what is
   large, and it is XIP from RTC RAM in this design.

Any of these is a scope decision, and it is the operator's, not the probe's.

---

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §4.3 — the shipping engine's measured size and the corrected verdict

```
**Does the shipping engine fit? (`P29`)** No. Built as specified — 16-bit code tokens (`P28`), `vm_switch`
and the 140 B records (`P27`), paging through `resolve()`/4 × 512 B frames (`P22`), the layer's four hooks
(`pl_key`, `pl_emit`, `pl_hw`, `pl_halt`) — the engine is **`.text` 4670 + `.rodata` 264 = 4934 B**, i.e.
**+1744 B over `P22`'s 3190**. The link at `MEMSZ` 908 fails with `address 0x25dc ... section '.bss' is not
within region 'ram'` — **1836 B over the 7856 B pool** — and `MEMSZ` 0 still fails by 918 B, so the pool,
not the dictionary, is the binding constraint. The overrun is the dispatch loop: `vm_enter` is **2380 B**
(51 % of the engine, including 61 primitives and the inlined paged fetch) and the switch's struct copy
pulls in **400 B of libgcc** (`memcpy` 232 + `memset` 168). `vm_switch` itself is **102 B** and the fault
path reuses it. Every budget array is present by symbol (`nm -S`: `frm` 2048, `ptab` 16,
`ptab_lru_reserve` 234, `cmd_ring` 128, `out_ring` 256, `mailbox` 216, `tib` 128, `mem` 908, `vm_live`
136 = the two 64 B stacks, `tsk` 420). The dictionary side is unaffected and still closes: `MEMSZ` 908 vs
resident need 676 = **+232 B** — a margin that no longer decides anything. `§4.3`'s closing row is
withdrawn pending a smaller primitive set (`P29` follow-up 1).
```

### 4.2 `docs/01-proposal.md` §10 — R4 restated: three tasks is not reachable on this engine

```
- [ ] **R4 — several tasks take turns, and the machine pays for them (`P27`, `P28`, `P29`).** The switch
      is one 140 B struct copy at `SD=16`, resumable mid-word, and the fault path shares it. The
      *arithmetic* closes at three tasks with 16-bit code tokens (`P28`: `MEMSZ` 908, resident need 676,
      **+232 B**), but the **engine that carries the switch does not fit**: `P29` measured it at
      **4934 B, +1744 B over `P22`'s 3190**, which is **1836 B over the 7856 B pool** with `MEMSZ` already
      cut to 908. The overrun is `vm_enter` (2380 B) and 400 B of libgcc from the struct copy, not the
      frames, stacks, rings or records — all of which are confirmed present by `nm -S`. **R4 is open
      until the primitive set is cut back to `P22`'s 40** (`P29` follow-up 1); the token width stays
      16 bits, and R5 is unaffected because data addresses were always 32-bit.
```

### 4.3 `docs/JOURNAL.md` — new entry

```
**The engine, measured with the switch in it, does not fit — by 1836 B.** P22 measured 3190 B of engine
with no context switch and no hooks; P27/P28 added the switch, the records and the width and left
232 B of dictionary margin. The shipping engine built here (16-bit tokens, `vm_switch`, paging, four real
hooks) is `.text` 4670 + `.rodata` 264 = **4934 B — +1744 B** — and the link at `MEMSZ` 908 stops 1836 B
past the 7856 B pool. Two things nobody costed: `vm_enter` at 2380 B (61 primitives, and `resolve()`/
`pg_load()` inlined at every stream read) and **400 B of libgcc** — `tsk[from].vm = *V` compiles to a
`memcpy` call (232 B) and `vm_task_init`'s zero loop to a `memset` call (168 B). The switch itself is
102 B and the fault path reuses it, so the brief's three suspects were all innocent. Allocation is
confirmed by `nm -S` for every array this time, including the two stacks, which are `vm_live`'s first
128 B and not symbols of their own. Decision: **the 232 B margin is not a margin on the engine** — it is a
dictionary margin, and the engine is charged to the pool. Rerun with P22's 40 primitives before §4.3 is
written again.
```

---

## 5. Follow-ups

1. **Build the same engine with P22's 40 primitives, not P27's 61.** The 21 extra (`J`, `UNLOOP`, `W@`, `W!`,
   `U/MOD`, `XOR`, `INVERT`, `LSHIFT`, `RSHIFT`, `U<`, `KEY?`, `W,`, `C,`, `LITERAL`, `".`, `(.")`, `(`,
   `MS`, `WAKE`, `PAUSE`, `FAULT`, …) are inside `vm_enter`'s 2380 B. This is the first experiment to run,
   and it is mechanical: the switch case list and `PRIMS` have to be cut together.
2. **Kill the libgcc 400 B.** `memcpy`/`memset` are pulled in by a 136 B struct copy and a 16-iteration
   zero loop. Either let the compiler see a smaller fixed copy (`-fno-tree-loop-distribute-patterns`
   keeps the loop inline) or make the record copy explicit word stores. 400 B is 0.8 % of the pool and
   22 % of the overrun; it is the cheapest single line in this table.
3. **Re-measure `pg_load`/`resolve` inlining.** `resolve()` is inlined into five call sites inside
   `vm_enter`; marking it `noinline` costs 1 call and may save more than it costs at `-Os` — P22 never
   had to answer this because its dispatch loop was smaller.
4. **Do not re-run P26's layer residency question until the engine fits.** At 1836 B over, the layer's
   1024 B is not the next decision, and P28's §2.4 already says a resident layer closes nothing.
5. **The brief's failure criterion is now the plan's problem, not the probe's:** "§4.3 changes, and the
   answer is likely two tasks or paging the cold prelude" — neither is enough (two tasks saves 140 B of
   1836; the cold prelude is dictionary, and the dictionary is not what overflows). The answer this probe
   produces is **"the engine's dispatch loop"**, with `vm_enter` 2380 B and libgcc 400 B named.
