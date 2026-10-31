# P35 — How big is the program when paging is dropped and the pool is re-spent?

| | |
| --- | --- |
| Result | **Paging dropped, the machine links at `MEMSZ` 2196 (C stack not reserved) and 1880 (320 B C stack carved inside the pool)** — both found by linking, not by arithmetic; 2197 and 1881 fail. With the language intact (D's 49 entries) and one 512 B block buffer plus its `BLKXFER` primitive in place, the operator's own words get **1008 B = 36 headerless words (25 with headers)** in the optimistic case and **692 B = 24 words (17 with headers)** in the honest one, against the paged machine's **232 B = 8 words (6 with headers)**: **+776 B, 4.3×** optimistic and **+460 B, 3.0×** honest. The "908 B" was an artefact: dropping paging returns **+1288 B of `MEMSZ`** (2196 vs 908), not the 1666 B the pool arithmetic promised, because a real block layer costs **352 B** (engine 348 + `blk_out` 4) where the probe allowed itself 200, and `MEMSZ > 2048` costs 6 B more of immediates. `nm -S` confirms it: `mem` = 0x894 (2196) / 0x758 (1880), and `frm`, `ptab`, `ptab_lru_reserve` are **gone**. What is now unbounded is data blocks in flash and source in flash; what is still bounded is **resident definitions**, because the interpreter fetches tokens from RTC RAM and executable code must be resident. |
| Runs on | **host only** — `riscv32-esp-elf-gcc 14.2.0 (esp-14.2.0_20241119)`, IDF v5.4, P29/P31's stub-subtraction recipe. Board untouched, no `/dev/ttyACM*` opened. |
| Time box | **inside 15 min, one run.** The whole build is a single 8 s `tmux`/`nice` run of `run.sh` (24 compile+link attempts, both conventions); the time went on reading P32/P33, not on building. |
| Sources | `src/` is **P33's `src/` copied verbatim** — it already contains this probe's variant as `-DP33_NOPAGE` + `-DP33_BLOCK` on P32's D, so **no engine source was edited**. New: `p35_build.py` (P32's driver, variant fixed to E, bisection on `MEMSZ`, `+1..+3` refinement), two link scripts copied from `ulp_p31.ld` with only the pool convention changed: `src/ulp_p35_opt.ld` (LENGTH 7856, `__stack_top` = region top) and `src/ulp_p35_stack.ld` (LENGTH 7536, `__stack_top` = 7856, the 320 B C stack carved *inside* the pool). |
| Artifacts | `logs/p35_build.log` (every attempt, timestamped), `artifacts/p35_{opt,stack}_nm.txt`, `artifacts/p35_{opt,stack}_{2196,1880}.{elf,map,bin}`, `artifacts/p35_control.{elf,bin}`, all intermediate `p35_{mode}_{memsz}.elf` |

## Record

| Case | `MEMSZ` | minus prelude (676) | minus prelude **and the 512 B block buffer** | words @28 B | words @39 B |
| --- | --- | --- | --- | --- | --- |
| paged machine, for reference (P28) | 908 | 232 | 232 *(frames were outside `mem[]`)* | ~8 | ~6 |
| **non-paged, C stack not reserved** | **2196** (2197 fails) | 1520 | **1008** | **36.0 → 36** | **25.8 → 25** |
| **non-paged, C stack reserved (320 B)** | **1880** (1881 fails) | 1204 | **692** | **24.7 → 24** | **17.7 → 17** |
| gain over the paged machine | +1288 / +972 | +1288 / +972 | **+776 (4.3×) / +460 (3.0×)** | +28 / +16 | +20 / +12 |

Both "minus prelude" columns are given because the 512 B buffer lives **inside** `mem[]` (`BLKADR = MEMSZ − BLKSZ`,
so no Forth word can be locked out of it) — quoting `MEMSZ − 676` alone would repeat exactly the kind of
convention error P32 found in §4.3. The paged machine's 232 B had no buffer inside `mem[]`, which is why its
last column equals the second.

## 1. Answers

### 1.1 The two maxima, by construction

`p35_build.py` starts at the P33-known-good 1420 (both conventions link there — the regression check), escalates
by a doubling step until a link fails, bisects to 4-byte granularity, then steps `+1/+2/+3` because `mem[]` is a
byte array and the `.bss` total need not end 4-aligned. Every reported boundary is a **linking image** with a
**failing image 1 B above it**:

| convention | links | fails | sections at the winner | left of the limit | `mem` (`nm -S`) |
| --- | --- | --- | --- | --- | --- |
| `opt` — LENGTH 7856, `__stack_top` = 7856 | **2196** | 2197 | 7853 of 7856 | 3 B | 0x894 = 2196 |
| `stack` — LENGTH 7536, `__stack_top` = 7856 | **1880** | 1881 | 7531 of 7536 | 5 B | 0x758 = 1880 |

The two maxima differ by **316 B**, not 320: `MEMSZ` 2196 > 2048 makes `P()`'s `a < MEMSZ` comparison grow a
`lui`+`addi` pair, which is **+6 B of engine** (engine 4096 → 4102; `nm` puts it in exactly the three
functions that compare an address against `MEMSZ` — `rd8` 30 → 32, `wr8` 30 → 32, `blk_sum` 50 → 52). Below
2048 the machine is 6 B cheaper, so the stack-honest case keeps 6 B of the 320.

### 1.2 What the machine costs with paging gone

| | D (P32, paged) | **E (P35, `P33_NOPAGE`) at `MEMSZ` ≤ 2048** | Δ |
| --- | --- | --- | --- |
| primitive entries | 49 | **49 (unchanged)** | 0 |
| engine, sections (`.text − control.text` + `.rodata`) | 3916 | **4096** | **+180** |
| engine, `.bin − control` | 3928 | 4110 | +182 |
| `pg_load` + `rd16_paged` | 108 + 60 | **0 (gone)** | −168 |
| block layer (`BLKXFER` cases, `BLKSUM`, `blocks.fs`'s names) | — | **+348** | +348 |
| `blk_out` | — | **4 B** | +4 |
| `frm` 2048 + `ptab` 16 + `ptab_lru_reserve` 234 | 2298 | **0 (gone)** | −2298 |
| `mem` | 908 | 2196 / 1880 | **+1288 / +972** |

`-168 + 348 = +180` accounts for the engine exactly. The block layer is therefore **352 B** (348 engine + 4
`blk_out`) — **152 B more than the 200 B this probe reserved itself**, which is where most of the shortfall
against P32's arithmetic comes from. 348 B for one primitive with a bounded poll, a checksum, a busy/nack/CRC
return path and five Forth wrappers is the honest price of "visible blocks"; P33 measured `blk_sum` 50 and
`blk_xfer` inlined at 0 B, so the rest is the `block.fs` dispatch and the mailbox arithmetic, not a leak.

### 1.3 The arithmetic cross-check, and the 378 B that did not appear

P32's model: 8656 needed at `MEMSZ` 908, minus 2466 for paging = 6190, so `MEMSZ` could rise by **1666** to 2574.
Measured: **+1288** to 2196. The 378 B is:

| line | bytes |
| --- | --- |
| block layer beyond the 200 B reserve: 352 − 200 | **152** |
| `MEMSZ` > 2048 immediates in `P()` | **6** |
| residue (`.rodata` name strings 228 vs D's 196 = +32 against control `.text` 214 vs P32's 196 = −18, `.bss` alignment) | **≈220 → measured 20 net** |

The exact statement, from the two images rather than a model: `sections = 5651 + MEMSZ` for E (7531 − 1880), and
`sections = 7748 + MEMSZ` for the paged D (8656 − 908). The pool-side saving is **2097 B** (7748 − 5651) where P32
priced 2466 − 352(block) − 6(lui) = 2108 → **11 B**, inside `.bss` alignment. **No byte of the 2466 went
missing**: 2091 of it came back and 352 of it was spent on the block layer that replaces the frames.

### 1.4 The operator's number

`MEMSZ` 2196 − 676 prelude − 512 buffer = **1008 B for the operator's own words**: **36 words headerless**
(28 B), **25 with headers** (39 B). Honest case, `MEMSZ` 1880: **692 B**, **24 words / 17 words**.
The paged machine gave them **232 B = 8 words / 6 words**. So: **4.3× more program, or 3.0× if the C stack is
paid for** — and what that means in absolute terms: **36 words is a program**, where the paged machine's
8 words were a demonstration.

## 2. Evidence

### 2.1 Commands (all under `timeout`; build in tmux with `nice -n 10`; every output inside this directory)

```sh
mkdir -p artifacts logs src
cp -r ../P33-visible-blocks/src/. src/          # P33's E, verbatim; no engine edit
python3 - <<'EOF'                               # the two link scripts, from ulp_p31.ld, pool line only
EOF
tmux new-session -d -s P35 './run.sh'           # timeout 290 nice -n 10 python3 p35_build.py 270
cat logs/p35_build.log
# nm -S written by the driver for each winner; the array check is one grep:
riscv32-esp-elf-nm -S artifacts/p35_opt_2196.elf   | awk '$4=="mem"||$4=="blk_out"'
riscv32-esp-elf-size -A artifacts/p35_{opt_2196,stack_1880,control}.elf
```

### 2.2 Allocation confirmed (`nm -S`, `artifacts/p35_{opt,stack}_nm.txt`)

```
opt  MEMSZ=2196: mem=2196 frm=GONE ptab=GONE ptab_lru_reserve=GONE tsk=420 tib=128 mailbox=216
                 out_ring=256 cmd_ring=128 vm_live=136 blk_out=4   sections 7853 of 7856 (3 left)
stack MEMSZ=1880: mem=1880 frm=GONE ptab=GONE ptab_lru_reserve=GONE tsk=420 tib=128 mailbox=216
                 out_ring=256 cmd_ring=128 vm_live=136 blk_out=4   sections 7531 of 7536 (5 left)
```

`mem` equals `MEMSZ` in both cases and the three paging arrays have no symbol at all. There is deliberately
**no `blkbuf` symbol**: the buffer is `mem[MEMSZ − 512 .. MEMSZ)`, which is the point (P33) — a separate
static array would be 512 B no Forth word can address.

### 2.3 Failure messages are links, not messages about the absence of a link

`stack 1881 -> LINK-FAIL first over-budget address 0x1d71`; `opt 2197 -> LINK-FAIL … 0x1eb1`. Both are the
linker refusing to place a section past `LENGTH`, i.e. the same evidence P32 used, and both maxima are the
attempt immediately below the first refusal.

## 3. Verdict

**The operator's program was never 232 B, and it is not 908 B either: it is 1008 B (36 headerless words) with
paging gone and the C stack unreserved, 692 B (24 words) if the C stack is honest.** On the probe's criteria:

* *maximum linking `MEMSZ` found by construction* — **met**: 2196 (`opt`, 2197 fails) and 1880 (`stack`, 1881
  fails), §1.1, each a linked image with a refused image around it.
* *the operator's-word budget in bytes and words, headerless and with headers* — **met**: 1008 / 36 / 25 and
  692 / 24 / 17 against the paged 232 / 8 / 6, §1.4, with the 512 B buffer subtracted separately because it sits
  inside `mem[]`.
* *the one-sentence statement of what scales* — **met**: §3.1.

Failure criteria, none triggered: the gain is **+1288 B**, far above the 500 B floor, so no accounting error;
the words figure is **36**, not under 40 — but only just, so §5.1 names the next lever; "**link fails at 908
too**" cannot have happened: 1420 links under both conventions and sections are monotone in `MEMSZ`, so 908
links a fortiori (it was not linked on its own — the search's floor is 1420, the P33-known-good point).

### 3.1 The sentence

**Data blocks are now unbounded and source lives in flash, but resident definitions are still bounded — the
interpreter fetches tokens from RTC RAM and executable code must be resident — so 36 words is what one RTC-pool
budget buys, and everything an operator writes *into blocks* or *loads as source* costs nothing from it.**

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §4.3/§4.4 — the re-spent budget

```
**The re-spent budget (`P35`, measured by link).** With paging dropped (P32 option (a)) and one 512 B block
buffer plus its BLKXFER primitive added, the machine links at `MEMSZ` **2196** with the C stack unreserved and
**1880** with the 320 B C stack carved inside the pool (2197 and 1881 fail). Paging was spending 2048 (frames)
+ 16 (`ptab`) + 234 (`ptab_lru_reserve`) + 168 (`pg_load`, `rd16_paged`) = 2466 B on a mechanism no Forth word
can see; the block layer that replaces it costs 352 B (348 engine + 4 `blk_out`).

| | paged (P28) | non-paged, stack not reserved | non-paged, stack reserved |
| --- | --- | --- | --- |
| `MEMSZ` | 908 | **2196** | **1880** |
| prelude (resident, 16-bit tokens) | 676 | 676 | 676 |
| 512 B block buffer (top of `mem[]`) | — | 512 | 512 |
| **available for the operator's own words** | **232** | **1008** | **692** |
| words @28 B headerless | ~8 | **36** | **24** |
| words @39 B with headers | ~6 | **25** | **17** |

The headline "908 B of Forth memory" is retired: it was what a pool that had already paid 2466 B for
transparent paging could afford. The machine's real figure is **1008 B / 36 words** (692 B / 24 words honest),
and the growing things are data blocks and source in flash, not definitions.
```

### 4.2 `docs/07-status.md` — the corrected headline

```
**Program size, corrected (`P35`).** "908 B of Forth memory" was a paging artefact, not a property of the chip:
the transparent-paging budget had already spent 2466 B of the 7856 B pool. Drop it and the same machine links
at `MEMSZ` **2196** (1880 with the 320 B C stack honoured), which is **1008 B / 36 headerless words** of room for
the operator's own definitions (692 B / 24 words honest) after the 676 B resident prelude and a 512 B block
buffer — **4.3×** the paged machine's 232 B. Data blocks and source do not live in that budget; only executable,
resident definitions do, because the interpreter fetches tokens from RTC RAM.
```

### 4.3 `docs/JOURNAL.md` — the number, and that 908 was a paging artefact

```
**The operator's program is 1008 bytes, not 232 — and the "908 B" was a paging artefact.** P28's 908 B came
from a pool that had already paid 2466 B for four page frames, a page table and a paged fetch channel, none of
which a Forth word can address or observe. Dropping paging (P32 option (a)) and spending 352 B on what actually
replaces it — one 512 B block buffer at the top of `mem[]` and the BLKXFER primitive, whose bounded poll is the
only part Forth cannot express — the same engine with the same 49 primitives links at `MEMSZ` **2196**, or 1880
if the 320 B C stack is carved inside the pool as it should be. After the 676 B resident prelude and the buffer,
that is **1008 B of room for the operator's own words: 36 headerless, 25 with headers**; honest case 692 B, 24
and 17. Against the paged machine's 232 B that is 4.3× (3.0×) — and the gain is measured, not computed: 2197 and
1881 fail to link. The lesson to keep is the one that cost the project its worst number: MEMSZ is meaningless
without the script it was linked under, and a budget line for a transparent mechanism is a line the operator
never sees.
```

## 5. Follow-ups

1. **36 words is a program but not a big one.** The next lever is not the pool: it is **source on flash** —
   `LOAD` from a `tib` filled by the main core means a 200-word program needs 200 × 28 B of *representation*
   nowhere, because the definitions still have to be resident. The lever that does move the number is
   **`FORGET`/compile-to-flash-of-headers**, and the one that moves it most is a bigger block buffer only if
   the buffer is where the program lives.
2. **`MEMSZ` 2196 is above the 2048 immediate boundary** and pays 6 B for it. If future work wants the last
   bytes, `P()` can compare against a runtime `memsz` word or `MEMSZ − 1` offsets; 6 B is not worth a change
   now, but it is free to know.
3. **The block layer is 352 B, not 200.** P33/P34 priced one primitive and one buffer; `blocks.fs`'s five
   wrappers and their name strings are the rest. If the layer is ever cut down, that is where to look — and
   `blk_out` 4 B is the only state it keeps.
4. **The stack convention is still unfixed in the shipping script.** `src/ulp_p31.ld` (and `ulp_p30.ld`) still
   set `__stack_top = ORIGIN + LENGTH` with `LENGTH = 7856`, i.e. the 320 B stack grows into the last of the
   image. P35 built the honest case with a separate script; the shipping script needs the one-line fix from
   P32 §5.1, or every future `MEMSZ` claim is 316 B optimistic (measured: 2196 vs 1880).
5. **P33 and P34 have no `RESULT.md`.** This probe read their numbers off `logs/p33_E.log` and
   `artifacts/p33_E_nm.txt`; if the visible-block layer is to be cited as measured, those two directories need
   their write-ups.
