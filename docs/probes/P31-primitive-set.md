# P31 — Does the layer need 61 primitives, or 40?

| | |
| --- | --- |
| Runs on | **host only** (build + link) |
| Time box | **15 min**, one run, hard cap |
| Depends on | P20 (40 prims = 3162), P29/P30 (61 prims = 4934) |
| Blocks | the port |
| Serves | R1–R5 |

## Question

P20 measured a 40-primitive engine at **3162 B**. P29 and P30 both built the shipping engine with **61
primitive bodies**. That is the whole difference between "over by 1836 B" and "fits with room", so it must be
settled: **which primitives does the P26 layer actually require**, and what does the engine cost with exactly
that set?

P30 established the cost is ~57 B per primitive body, so **21 primitives is roughly 1 200 B** — the single
largest lever left.

## Why it matters

If the layer compiles against 40, the machine fits. If it needs 61, the machine does not, and the difference
has to be paid by dropping paging or a task — a scope decision. Either answer ends the budget phase.

## Given — do not re-derive

* P20: variant C = 40 primitives, engine **3162**, prelude dictionary 1716, dispatch 726 cycles.
* P29: shipping engine with 61 bodies = **4934**; `vm_enter` 2380; libgcc 400.
* P30: out-of-line bodies cost **3540** for the same 62, i.e. ~57 B each, anywhere. Hand VM copy + unrolled
  zero saves **400 B**.
* P26: the minimal layer, 22 definitions, compiled against the **40**-primitive set.
* Target: engine ≤ **3438 B** for 4 frames + 3 tasks.

## Method

1. Take P29's shipping source (16-bit tokens, `vm_switch`, paging, 3 task records, four hooks).
2. **Determine the requirement, do not assume it.** Compile P26's layer against the engine with the 40-set and
   record every primitive it names. Then list the primitives P29's 61 include that the layer never uses, and
   for each say what would break if it were removed (a prelude word? a primitive that another primitive
   calls?).
3. Build three variants, each linked at `MEMSZ` 908 with 3 tasks, allocation confirmed by `nm -S`:
   - **A** P29 baseline with 61 — must reproduce 4934;
   - **B** exactly the set the layer plus the prelude requires (expect ~40, but state the measured number);
   - **C** B + the hand VM copy and unrolled zeroing from P30 variant D (−400 B).
4. Report each engine's size, its gap to 3438, and whether the **real 7856 B link succeeds**.
5. For the set in B, report what was removed and the functional consequence of each removal in one line.

## Record

| Variant | primitives | engine | gap to 3438 | links at 7856? |
| --- | --- | --- | --- | --- |
| A | 61 | 4934 | +1496 | no |
| B | *measured* | | | |
| C | *measured* | | | |

Plus: the removed primitives with their consequence, and the `nm -S` allocation check.

## Pass criteria

* the required primitive set **derived from what the layer and prelude actually name**, not from a guess;
* A reproduces 4934;
* C's engine at or under **3438** with a successful real link, or the exact remaining gap.

## Failure criteria — and what each changes

* **C fits** ⇒ the machine is buildable. Report the final engine figure and hand the numbers to the port.
* **C still > 3438** ⇒ report the gap and stop guessing: the options are (i) drop paging from the first
  machine (~1 000 B of `resolve`/`pg_load`/`read path` plus the frames' 2 048 B back to the pool), (ii) two
  tasks (−140 B), (iii) a smaller prelude. **Present them with measured cost and let the operator choose.**
  Do not pick one.
* **The layer needs > 50 primitives** ⇒ say which ones and why; the 40-set from P20 was then optimistic and
  §4.3 must record the real requirement.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.3 — the required primitive set, the engine size, and whether the machine fits.
* `docs/JOURNAL.md` — the resolution of the 61-vs-40 discrepancy.

## Do not

* Do not remove a primitive that a prelude word needs without naming the prelude word that dies.
* Do not touch the board, `docs/`, or other probes' directories.
