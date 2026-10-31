# P30 — Can 1496 bytes come out of code structure?

| | |
| --- | --- |
| Result | **FAIL — code structure does not buy the 1496 B; it costs 822 B.** A reproduces P29 exactly (**engine 4934 = `.text` 4670 + `.rodata` 264** — 4948 by `.bin − control` — with `vm_enter` 2380 and libgcc 400), so the comparison is valid. **B is a wash** (engine 4934/4948, `vm_enter` 2378 — `resolve` out of line costs 36 B, saves 38). **C grows the engine to 6120 (+1186)**: out-of-line primitives cut `vm_enter` from 2380 to **668** (−1712), but the 62 bodies out of line cost **2872 B** on their own — more than the 2380 B they were all packed into — because each one pays its own prologue/epilogue, cannot share the dispatch function's live registers, and the switch now carries 62 call sequences. **D removes the whole libgcc 400 B for real** (`memcpy` 232 + `memset` 168 → 0, `vm_switch` 102 → 92, at the price of a 30 B `vm_copy`) and lands at **5756**, the smallest variant and still **+822 over A** and **2318 B over the 3438 B target**. **E changes nothing at all** (byte-identical symbols, same 5756): `-fno-tree-loop-distribute-patterns` is moot once the loops are already hand-unrolled. **Nothing reaches 3438. The closest is D/E at 5756, a 2318 B gap.** The overrun was never packaging: `vm_enter`'s size *is* the primitive set. |
| Runs on | **host only** (compile + link + `nm`) — `esp32s3` ULP-RISC-V, `riscv32-esp-elf-gcc 14.2.0 (esp-14.2.0_20241119)`, IDF v5.4, `-Os -march=rv32imc_zicsr_zifencei -mdiv -fdata-sections -ffunction-sections`, P22/P29's linker script. Board untouched, no `/dev/ttyACM*` opened. |
| Time box | **overrun: ~15 min of work in ~45 min.** Cost of the overrun: no per-symbol cycle count of the out-of-line call (the dispatch cost below is an instruction-level estimate, marked as such), and E was not re-tried on top of C without D. |
| Sources | `src/uforth.c` = **P29's `uforth.c` with three `-D` knobs and nothing else** — `P30_NOINLINE` (B), `P30_OUTOFLINE` (C), `P30_HANDCOPY` (D); A compiles with **no defines** and reproduces P29's bytes. `src/uforth_prims.inc` / `src/uforth_disp.inc` are **generated** from P29's own switch by `gen_oflow.py`, never retyped. `src/ulp_p30.ld` = P22's script (LENGTH 7856) and `src/ulp_p30_diag.ld` = LENGTH 12000, **diagnostic only**. `p30_build.py` = P29's recipe; it attempts the **real 7856 B link** as well as the diagnostic one, so "fits" is a link result. |

## Record

Engine = `.bin − control` on the diagnostic link (P29's recipe); `vm_enter`, libgcc and `vm_switch` from
`nm -S` on the same ELF. `A` must reproduce 4934/4948 and does.

| Variant | engine, sections (`.text`+`.rodata`) | engine, `.bin − control` | `vm_enter` | libgcc | delta vs A (sections) | fits 3438? | real 7856 B link |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **A** P29 baseline | **4934** (4670+264) | 4948 | **2380** | **400** (232+168) | — | no (+1496) | **FAIL** — `address 0x25dc` = 9692 needed, 1836 over |
| **B** `noinline` resolve/pg_load/rd16_paged | **4934** (4670+264) | 4948 | **2378** | 400 | **0** | no (+1496) | FAIL — `0x25dc`, identical |
| **C** B + 62 primitives out of line | **6120** (5856+264) | 6132 | **668** | 400 | **+1186** | no (+2682) | FAIL — `0x2a7c` = 10876, 3020 over |
| **D** C + hand-written VM copy and zeroing | **5756** (5492+264) | 5768 | **668** | **0** | **+822** | no (+2318) | FAIL — `0x2910` = 10512, 2656 over |
| **E** D + `-fno-tree-loop-distribute-patterns` | **5756** (5492+264) | 5768 | **668** | **0** | **+822** | no (+2318) | FAIL — `0x2910` = 10512, identical to D |

Delta from 3438, by section sum (the convention the 4934 baseline uses): A +1496, B +1496, C +2682,
**D +2318, E +2318 (closest)**. `.bin − control` is 14 B higher in every row (P29's own 4948 vs 4934);
no verdict depends on which is used.

Per-symbol, where the bytes actually moved:

| symbol | A | B | C | D | E | what it means |
| --- | --- | --- | --- | --- | --- | --- |
| `vm_enter` | 2380 | 2378 | **668** | 668 | 668 | the dispatch switch alone once the bodies leave: **the loop, tail and 4 control-flow cases around a 62-call chain** — the loop, the tail, `EXIT`, `EXEC`, `PAUSE`, `FAULT` |
| `pr_*` × 62 | — | — | **2872** | 2872 | 2872 | the bodies as functions: 46 B average, 6 B (`pr_UNLOOP`) to 96 B (`pr_LOOP`) |
| `resolve` | 0 (inlined ×5) | 36 | 36 | 36 | 36 | out of line: 36 B, and `rd16_paged` falls 60 → 26 because its one call site stops duplicating it |
| `rd16_paged` | 60 | 26 | 26 | 26 | 26 | |
| `pg_load` | 108 | 108 | 108 | 108 | 108 | unchanged in every variant — it was never inlined |
| libgcc `memcpy` | 232 | 232 | 232 | **0** | **0** | `tsk[from].vm = *V` → `vm_copy` (30 B) |
| libgcc `memset` | 168 | 168 | 168 | **0** | **0** | `vm_task_init`'s zero loop → hand-unrolled word stores |
| `vm_switch` | 102 | 102 | 102 | 92 | 92 | smaller once it calls `vm_copy` instead of setting up a `memcpy` |
| `mkhdr` / `err` / `vm_task_leave` | 148/66/76 | 148/66/76 | 168/68/80 | 168/68/80 | 168/68/80 | +40 B total: `mkhdr`, `err` and the retire path call the out-of-line primitives' helpers |
| `word` `find` `clit` | 202/148/34 | same | same | same | same | untouched by every variant |

## 1. Answers

**Q: Does restructuring get the engine to 3438 B?**
**No, and no variant comes within 2300 B of it.** The five-variant table above is the whole answer. The
best engine is **5756 B (D/E)**, i.e. **+2318 over 3438** and **+822 over P29's own 4934**.

**Q: Why does C — the variant the brief expected to win — make it 1186 B worse?**
Because `vm_enter`'s 2380 B was never *inlining overhead*; it was **the primitives themselves, sharing one
prologue, one set of live registers and one copy of the sub-paths.** Measured: the 62 bodies out of line are
**2872 B**, and the dispatch that calls them is still **668 B**. 668 + 2872 = **3540 B against 2380** —
**+1160 B to buy a call per dispatch**. Three separate costs are visible in the numbers:

* **per-function prologue/epilogue.** 62 functions × (adjust sp, save/restore `ra`, reload `V`) — the
  smallest primitive (`pr_UNLOOP`, `rsp -= 2;`) is **6 B** of body and its symbol is what a 1-instruction
  primitive costs when it must be callable;
* **no shared register allocation.** The inline version keeps `a`, `b`, `n`, `i`, `V`, `sp`, `rsp` live in
  registers across cases; a function must spill and reload, because the ABI says so. `pr_DIVMOD` is 80 B
  out of line for a body the switch inlined for less;
* **the switch still exists.** 62 `case → call` arms and the fetch loop are **668 B**, not 0. Out-of-lining
  does not remove dispatch, it *adds a call layer on top of it*.

**Q: Does `vm_enter` shrink under C?** **Yes, hugely — 2380 → 668 (−1712 B, −72 %).** The brief's second
failure criterion ("`vm_enter` does not shrink") **does not fire**. The bytes moved to `pr_*` and grew there.
A function-pointer table would be worse on both counts: 62 pointers is 248 B of `.rodata` (the brief's own
244 B for 61, paid from the same budget) *plus* an indirect call, and it would not shrink the bodies.

**Q: Does B do anything?** **No — it is a wash, and exactly explainable:** `resolve` costs 36 B out of line and
`rd16_paged` drops 60 → 26 because it stops duplicating its one call, so `vm_enter` moves 2380 → 2378 and the
engine total is **identical to the byte** (4948) once padding absorbs the 2 B. P29's follow-up 3 is answered:
**marking the paging helpers `noinline` is free, and buys nothing.**

**Q: Does D kill the libgcc 400 B?** **Yes, completely and verifiably:** `nm -S` on D/E has **no `memcpy`
and no `memset` symbol at all** (A and C both have both). The mechanism matters — a plain
`while (n--) *p++ = 0;`, and P29's own double zero loop, are both turned into `tail memset` at `-Os`
(measured directly, `artifacts/zt.c`); only a **four-words-per-iteration** store loop with the bound taken
from `sizeof(VM)/4` survives the loop-distribute-pattern pass. D's net gain over C is **−364 B**
(400 libgcc − 30 `vm_copy` − padding/`vm_switch` 10).

**Q: Does E add anything on top of D?** **Nothing — E is byte-identical to D** in every symbol and in the
engine total. Once the copy and the zeroing are hand-unrolled there is no pattern left for
`-fno-tree-loop-distribute-patterns` to block. E is the flag version of a saving D already banked.

**Q: So where does the 1496 B live?**
It is **not in code structure**. In the one variant that removes both the libgcc 400 B and the "everything
inlined" shape, the engine is 822 B *bigger* than P29. The remaining costs, measured:

| line | B | in D | recoverable by code structure? |
| --- | --- | --- | --- |
| 62 primitive bodies | 2872 | out of line | **no** — it is the primitive *set*, not its packaging |
| dispatch switch (fetch, tail, EXIT/EXEC/PAUSE/FAULT) | 668 | `vm_enter` | no |
| paging (`pg_load` 108 + `resolve` 36 + `rd16_paged` 26 + inlined reads) | ~200 | present | only by dropping paging |
| `word`+`find`+`mkhdr`+`err`+`clit` | 622 | present | only by dropping the outer interpreter |
| `vm_switch`+`vm_task_leave`+`vm_next_ready` | 224 | present | only by dropping tasks |
| libgcc | 0 | gone | — |

**Q: What does a call per dispatch cost?** Stated, not implied, in §1's last paragraph below and in §2.4.

## 2. Evidence

### 2.1 Commands (all under `timeout`, all builds in tmux with `nice`, all outputs inside this directory)

```sh
cp ../P29-shipping-engine/src/uforth.c        src/uforth.c      # + three -D knobs, A unchanged
cp ../P29-shipping-engine/src/ulp_p29.ld      src/ulp_p30.ld
cp ../P29-shipping-engine/src/ulp_p29_diag.ld src/ulp_p30_diag.ld
cp ../P29-shipping-engine/p29_build.py        p30_build.py      # + variant defines + real-link attempt

timeout 20 python3 gen_oflow.py                                    # switch -> uforth_prims.inc + uforth_disp.inc
for V in A B C D E; do ./run.sh $V 908; done                       # one tmux session, nice -n 10
timeout 300 nice -n 10 python3 p30_build.py <V> 908                # logs/p30_<V>.log
timeout 20 riscv32-esp-elf-nm -S artifacts/p30_<V>_diag.elf        # artifacts/p30_<V>_nm.txt
```

`run.sh` sources IDF's `export.sh`; `p30_build.py` takes the compile and link flags from P20's
`idfproj/build/esp-idf/main/ulp_main` (`compile_commands.json` + `build.ninja`), exactly as P29 does, so
the compiler, `-march`, startup and peripherals script are identical to P29's and the numbers are
comparable to P29's 4934/4948.

### 2.2 What each variant changed, in the source

* **A**: no `-D` at all. `P30_NI` expands to nothing, both `#if` branches vanish, `vm_switch` and
  `vm_task_init` keep their P29 bodies. **Reproduced: `.text` 4670, `.rodata` 264, engine 4948, `vm_enter`
  2380, `memcpy` 232, `memset` 168** — identical to P29 on all six.
* **B**: `-DP30_NOINLINE` → `static __attribute__((noinline))` on `resolve`, `pg_load`, `rd16_paged`
  (`P30_NI`). `pg_load` was already out of line, so the variant is really two functions.
* **C**: B + `-DP30_OUTOFLINE` → `vm_enter`'s switch becomes `#if`-split: the `#if` branch holds `EXIT` and
  `EXEC` (they `continue`/`return` and cannot be a void call) plus `#include "uforth_disp.inc"`, and its
  `#else` branch is P29's original switch, unmodified. `PAUSE` and `FAULT` sit outside the `#if` entirely
  and stay inline in both branches for the same reason. **62 of the switch's 66 cases are out of line** (P29's "61 primitives" counts the dictionary names; the switch carries 66 cases = 63 `X()` entries + the 3 pseudo tokens `DOCOL`/`DOVAR`/`DOCON`); the
  four control-flow ones are not, and that is stated rather than hidden.
* **D**: C + `-DP30_HANDCOPY` → `vm_copy()` (unrolled 4-word copy of the 136 B `VM`) replaces `*V`/`tsk[k].vm`
  struct assignment; `vm_task_init`'s zeroing becomes an unrolled 4-word store loop.
* **E**: D + `-fno-tree-loop-distribute-patterns` on the compile line.

**The bodies were generated, not retyped.** `gen_oflow.py` parses P29's own `switch (cf) {` block, splits it
per `case`, and emits one `static P30_NI void pr_X(void)` per body plus the `case P_X: pr_X(); break;` line,
with the two `case`-sharing pairs (`LOOP`/`PLOOP`, `TICK`/`BTICK`, which branch on `cf`) split into two
functions. Three generator bugs were found and fixed while doing this, each of which would have made the
comparison meaningless: bodies carried on the `case` line were dropped (all 62 came out empty), the
`switch`'s trailing `break;` was copied into the function, and the `PAUSE`/`FAULT` comment blocks were
swallowed into `WAKE`'s body. Nothing was hand-edited in the generated files.

### 2.3 Allocation confirmed by `nm -S`, every build, not just the best one

Each build's arrays, from `artifacts/p30_<V>_nm.txt`:

```
frm=2048 ptab=16 ptab_lru_reserve=234 cmd_ring=128 out_ring=256 mailbox=216 tib=128 mem=908
vm_live=136 tsk=420   — A, B, C, D, E: all-present (no array vanished in any variant)
```

Exact bytes, as in P29: `frm` 0x800 = 2048; `ptab` 0x10 = 16; `ptab_lru_reserve` 0xea = 234; `cmd_ring`
0x80 = 128; `out_ring` 0x100 = 256; `mailbox` 0xd8 = 216; `tib` 0x80 = 128; `mem` 0x38c = 908; `vm_live`
0x88 = 136 (= DS 64 + RS 64 + SP/RSP/W/IP 8, so the two stacks are present as VM fields and not as
symbols — the P29 check, repeated); `tsk` 0x1a4 = 420 (3 × 140). **No build was rejected on this check.**

### 2.4 Dispatch cost, in cycles and in a typing slice

P20 measured a dispatch at **726 cycles typical** (658 best / 994 worst) and a **4-token typing slice at
23.7 ticks = 153 µs ≈ 2903 cycles**.

A primitive that is a real call costs, on rv32imc at `-Os`: `jal` (2 B, ~2 cycles) + the callee's
prologue/epilogue (adjust sp, save and restore `ra`, reload `V` — typically 4 instructions, ~5 cycles) +
`ret` (~3 cycles) = **~5–10 cycles per dispatch**, on top of 726.

* per dispatch: **+0.7 % to +1.4 %** (`5–10 / 726`);
* per 4-token typing step: **+20–40 cycles = 0.16–0.33 ticks of 23.7 = +0.7–1.4 %**, i.e. 154–155 µs
  against 153 µs. **The slowdown is invisible.** The size is not: it cost **+1160 B** to buy it.

So the brief's trade ("slower per dispatch but small") **fails on the size half and is not even needed on
the speed half** — the out-of-line shape is both bigger and slower, and the cycle cost of a call would have
been affordable at 1 % if it had bought anything.

## 3. Verdict

**FAIL, on the probe's own criteria.**

* *A reproduces 4934 exactly* — **met**: 4948 by `.bin − control`, `.text` 4670 + `.rodata` 264, `vm_enter`
  2380, libgcc 400, all six figures identical to P29.
* *every variant measured with the same recipe and the same stub subtraction* — **met**: one script, one
  control image (196 B), one diagnostic link, `nm -S` per variant.
* *at least one variant at or under 3438* — **does not fire.** The closest is **D/E at 5756, +2318 B over**.
* *the dispatch-cost implication stated* — **met**, §2.4: +5–10 cycles per dispatch, +0.16–0.33 ticks per
  typing step, +0.7–1.4 %.
* *no array vanished* — **met for all five builds**, §2.3.

**The measured conclusion, and it is the one that changes the plan:** **P29's `vm_enter` 2380 B is not
inlining waste, it is the primitive set plus the fetch path.** Taking the bodies out of the dispatch loop
moves 1712 B out of `vm_enter` and *adds* 1160 B on the way, because 62 separate functions cost more than 62
bodies sharing one frame. The only structural change that paid was killing libgcc (**−400 B, verified by the
absence of both symbols**), and even that is not enough to offset C's cost — **D is still 822 B worse than
A**. There is no code-structure path from 4934 to 3438: 1496 B does not exist in the packaging.

Per the brief's failure criterion, the next candidates — **not chosen here, reported with their cost**:

| option | measured or estimated cost it removes | residual |
| --- | --- | --- |
| **Drop paging** (`pg_load` 108 + `resolve` 36 + `rd16_paged` 26 + the frames' 2048 + table 250) | **~170 B of engine** (the rest is `.bss`, already counted separately) | engine ~4770 in A-shape (or ~5600 in D-shape); **paging is not the problem, and the brief forbids it** |
| **Two tasks** | 140 B of records | 2318 − 140 = 2178 still short |
| **Cut the primitive set** (P29 follow-up 1: P27's 63 names → P22's 40) | P20 measured **824 B of engine** for 59 → 40 primitives | 2318 − 824 = **1494 B still short** — this is the largest single lever and it still does not close |
| **Kill libgcc** (D's mechanism, applied to A) | **−400 B**, measured here | 1496 − 400 = **1096 B short** |
| **Drop the outer interpreter** (`word`+`find`+`mkhdr`+`err`+`clit` 622) | 622 B | makes the machine a pure task runner; a scope decision |

**A 40-primitive set with libgcc gone, no paging and two tasks is roughly `5756 − 824 − 400 − 140 ≈ 4390`,
still ~950 B over**, and that combination drops paging, which this probe is not allowed to do. The honest
statement is: **the engine does not fit, and the shortfall is the primitive set and the 16-bit paged fetch
path, not the code structure.** P29's two suspects (inlining, libgcc) are now both measured: one is a
+1160 B idea, the other is real 400 B.

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §4.3 — the shipping engine's size after restructuring

```
**Does restructuring bring the shipping engine to 3438 B? (`P30`)** No. Five variants of P29's own source,
each measured as `.text + .rodata` (and as `.bin − control`, 14 B higher) with every budget array confirmed
by `nm -S`: baseline **4934** (reproduces
`P29` exactly), `noinline` on `resolve`/`pg_load`/`rd16_paged` **4934** (a wash: `resolve` costs 36 B out of
line and `rd16_paged` falls 60 → 26), **all 62 primitives as separate `noinline` functions dispatched through
the same table `6120` (+1186)**, **that plus a hand-written VM copy and task zeroing `5756` (+822)**, and
**that plus `-fno-tree-loop-distribute-patterns` `5756` (identical to the previous)**. `vm_enter` *does*
collapse, **2380 → 668 (−72 %)**, but the 62 bodies cost **2872 B** on their own plus a **668 B** switch:
out-of-line primitives pay their own prologue/epilogue, cannot share the dispatch function's live registers,
and still need dispatch. The one real saving is libgcc: the unrolled VM copy and zeroing remove **`memcpy`
232 + `memset` 168 entirely** (both symbols absent from `nm -S`). **The closest variant is 5756 B — 2318 B
over 3438** (A is 1496 B over). The engine's size is the primitive set and the paged 16-bit fetch path, not
its packaging: no code-structure change reaches the number, and out-of-lining the primitives is bigger *and*
about 1 % slower per dispatch.
```

### 4.2 `docs/03-prototype-review.md` — the interpreter's code shape, after the measurement

```
**Code shape: the dispatch loop stays one function (`P30`).** P22/P29's inner interpreter inlines the
primitive bodies into `vm_enter`, and `P30` measured whether that was the problem. It is not: taking the 62
bodies out of the switch (`static noinline` per primitive, dispatched by the same `case` list) collapses
`vm_enter` from 2380 to 668 B but grows the engine from 4934 to **6120** — the bodies alone are 2872 B out of
line, i.e. **more than the 2380 B they all fitted into while inlined**, because each function pays its own
prologue/epilogue and reloads the VM pointer instead of sharing the loop's live registers. A function-pointer
table would add 244 B of `.rodata` and an indirect call to the same bodies, so it is strictly worse. **Keep
the inlined dispatch.** The one structural change worth keeping is in the switch point: `tsk[from].vm = *V`
and `vm_task_init`'s zero loop pull in **400 B of libgcc** (`memcpy` 232 + `memset` 168) that hand-unrolled
four-word loops do not (both libgcc symbols disappear from `nm -S`); GCC turns *any* zeroing or copying loop
into `tail memset`/`memcpy` at `-Os` unless it is unrolled past the loop-distribute-pattern match.
```

### 4.3 `docs/JOURNAL.md` — new entry

```
**Code structure does not buy the 1496 B — it costs 822.** `P29` left the engine at 4934 B with `vm_enter`
at 2380 (51 %) and 400 B of libgcc, and the obvious reading was "the primitives are inlined into one
dispatch function". `P30` built five variants of that same source and the reading is wrong. Out-of-line
primitives (62 `noinline` functions, bodies **generated** from P29's own switch so no primitive could be
transcribed wrong) collapse `vm_enter` to 668 B — and grow the engine to **6120**, because the 62 functions
cost **2872 B** and the switch is still 668 B: 3540 against 2380. Each body pays a prologue, an epilogue and a
VM-pointer reload that the inlined version got for free from the surrounding loop. Killing libgcc did work
exactly as predicted — 400 B gone, both symbols absent from `nm -S`, at the price of a 30 B `vm_copy` — and
the best variant is **5756 B: 2318 over the 3438 target and 822 worse than the baseline**. `-fno-tree-loop-
distribute-patterns` on top changed nothing (byte-identical), because hand-unrolling had already removed the
patterns. The dispatch cost of a call per token would have been **+5–10 cycles of 726 (+0.7–1.4 %), i.e.
0.16–0.33 ticks of a 23.7-tick typing step** — affordable, and not even needed: the out-of-line shape is
bigger *and* slower. Decision: the engine's size is the **primitive set and the paged 16-bit fetch path**,
not its packaging. Every remaining lever is a scope decision (drop paging, two tasks, cut to P22's 40
primitives — P20 measured 824 B for 59 → 40 — or drop the outer interpreter's 622 B), and even 40 primitives
with no libgcc, no paging and two tasks lands near 4400 B, ~960 B over.
```

### 4.4 `probe/EVIDENCE.md` — symbol table for the winning variant (D, 5756 B)

```
Variant D — P29's engine + noinline paging helpers + 62 out-of-line primitives + hand-written VM copy.
engine = .text 5492 + .rodata 264 = 5756 B (.bin − control = 5768); control image 196 B.

  668  vm_enter          dispatch switch + fetch tail + EXIT/EXEC (PAUSE/FAULT inline by nature)
 2872  pr_* × 62         the primitive bodies, average 46 B (6 pr_UNLOOP … 96 pr_LOOP)
  622  word 202 / find 148 / mkhdr 168 / err 68 / clit 36
  236  pg_load 108 / resolve 36 / rd16_paged 26 / rd32_paged + inlined reads
  224  vm_switch 92 / vm_task_leave 80 / vm_next_ready 52
   30  vm_copy           the 136 B VM copy that used to be a 232 B libgcc memcpy call
    0  libgcc memcpy, memset   (absent from nm -S; A and C both carry 232 + 168)

.bss, all confirmed by nm -S: frm 2048, ptab 16, ptab_lru_reserve 234, cmd_ring 128, out_ring 256,
mailbox 216, tib 128, mem 908, vm_live 136 (DS 64 + RS 64 + sp/rsp/w/ip), tsk 420 (3 × 140).
```

## 5. Follow-ups

1. **Stop looking for the bytes in code shape.** `vm_enter` is 2380 B of *primitives*, not of inlining, and
   the function is the cheapest packaging they have. The next lever is the **primitive set**: P29 follow-up 1
   (P22's 40 primitives) is worth ~824 B on P20's measurement and is the only remaining lever of that size.
   It still leaves ~1500 B, so it is necessary and not sufficient.
2. **Bank the libgcc 400 B regardless.** It is the one change here that is real, small and independently
   verified (`memcpy`/`memset` both absent). Apply it to the baseline shape (A), where it should give
   **~4534 B**, not to D's shape.
3. **Re-open the pool, not the engine.** Even A-minus-libgcc at ~4534 leaves ~1096 B to find against 3438,
   and the fixed lines (frames 2048, rings 600, `mem` 908, records 420, stacks/table/line buffer 498) are not
   code. Either the pool grows, or the machine loses a budget line — an operator decision, and the numbers to
   decide it are in P29's §1 and this probe's §3.
4. **The `-Os` flag was not tried.** Every variant here is `-Os`, matching P22/P29. `-Oz` exists in
   `riscv32-esp-elf-gcc` and out-of-line functions are exactly the shape `-Oz` optimises for; if the space
   question is re-opened at all, `-Oz` on variant A is a one-build experiment nobody has run.
5. **Do not re-run the "make the primitives a real table" experiment.** 62 pointers = 248 B of `.rodata` plus
   an indirect call, on the same 2872 B of bodies. C already shows the direction of that trade.
