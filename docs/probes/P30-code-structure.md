# P30 — Can 1496 bytes come out of code structure?

| | |
| --- | --- |
| Runs on | **host only** (build + link + `nm`) |
| Time box | **15 min**, one run, hard cap |
| Depends on | P29 (engine 4934, target 3438) |
| Blocks | the port — everything else is measured |
| Serves | R1–R5 |

## Question

P29's engine is 4934 B; a 4-frame, 3-task machine can afford **3438**, so **1496 B must go**. The attribution
says where it is: **`vm_enter` is 2380 B (51 %)**, because the 61 primitive bodies and the paging helpers are
inlined into one dispatch function, and libgcc `memcpy`/`memset` add another 400 B for copying a VM struct and
zeroing a task.

Can that be recovered **without** giving up paging, tasks, or 16-bit tokens?

## Why it matters

This is the difference between a machine that exists and a design document. And the shape of the fix matters:
if out-of-line primitives recover the bytes, the interpreter becomes a table of small functions — slower per
dispatch but small. If they do not, paging or tasks must go.

## Given — do not re-derive

* P29: engine 4934 = `.text` 4670 + `.rodata` 264; `vm_enter` 2380; libgcc `memcpy` 232 + `memset` 168;
  `vm_switch` 102; `pg_load` 108; `rd16_paged` 60; `word` 202; `find` 148; `mkhdr` 148; `err` 66; `clit` 34;
  hooks 196 (subtracted from the engine figure).
* P29: target engine **3438 B** = 7856 pool − frames 2048 − VM/table 400 − rings 600 − C stack 320 − hooks 142
  − `mem` 908.
* The allocation check must stay: `nm -S` for every budget array, every build.
* P20 measured that dispatch cost is dominated by the fetch path, so a small per-dispatch slowdown from
  out-of-line primitives is acceptable if it buys 1.5 KB.

## Method

Build variants of the **same source**, each measured the same way (engine = `.bin − control`, allocated arrays
confirmed by `nm -S`), and report the engine total plus the per-symbol delta:

| Variant | Change |
| --- | --- |
| **A** | P29 baseline — must reproduce 4934 |
| **B** | `resolve`, `pg_load`, `rd16_paged` marked `noinline` |
| **C** | B + all 61 primitives as separate `noinline` functions (dispatch through the existing table rather than inlining bodies) |
| **D** | C + hand-written VM copy and task zeroing (no libgcc `memcpy`/`memset`) |
| **E** | D + `-fno-tree-loop-distribute-patterns` (so GCC cannot re-introduce `memset` from loops) |

For the best variant, also report the **dispatch-cost** implication in words: what does the extra call per
dispatch cost at 726 cycles (P20), i.e. roughly how many cycles and therefore how much of a 23.7-tick typing
slice.

## Record

| Variant | engine total | `vm_enter` | libgcc | delta vs A | fits 3438? |
| --- | --- | --- | --- | --- | --- |
| A | 4934 | 2380 | 400 | — | no |
| B | | | | | |
| C | | | | | |
| D | | | | | |
| E | | | | | |

Plus: allocation confirmed per array for each build (or state that it was checked only for the best one), and
the estimated dispatch-cost delta.

## Pass criteria

* A reproduces 4934 exactly (otherwise the comparison is void);
* every variant measured with the same recipe and the same stub subtraction;
* at least one variant at or under **3438 B**, or an explicit statement of the closest and the remaining gap;
* the dispatch-cost implication stated, not implied.

## Failure criteria — and what each changes

* **Best variant still > 3438** ⇒ report the gap and the symbol responsible. The next candidates in order:
  drop paging from the first machine (frames + `resolve` + `pg_load` + the inlined read path), or drop to two
  tasks (−140 B), or a smaller layer. Do **not** choose unilaterally — report the options with their measured
  cost.
* **`vm_enter` does not shrink under C** ⇒ the inlining is happening for a reason (`static` + single call
  site). Say why, and whether making the primitives a real table (function pointers) is the only way.
* **Transitioning to a table blows up `.rodata`** ⇒ report both numbers; a 61-entry table of pointers is 244 B
  and would be paid from the same budget.
* **Any array disappears from `nm -S`** ⇒ invalid build; `FAIL`, fix, re-measure.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.3 — the shipping engine's size after restructuring, and whether the machine fits.
* `docs/03-prototype-review.md` — a note on the interpreter's code shape if it changed (table of functions vs
  inlined dispatch).
* `probe/EVIDENCE.md` — a symbol table for the winning variant.

## Do not

* Do not drop paging, tasks, or 16-bit tokens to hit the number — this probe is about code structure only.
* Do not touch the board, `docs/`, or other probes' directories.
