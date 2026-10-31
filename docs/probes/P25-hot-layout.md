# P25 — Can a hot-set layout rule make the idle loop fault-free?

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P24 (idle loop touches 6 pages, 6 faults/pass) |
| Blocks | R3/R4 — whether the loop can run without thrashing |
| Serves | R3, R4 |

## Question

P24 measured the OS layer's idle event loop touching **6 pages** and faulting **every pass** with 4 frames.
Two of the remedies are layout, not code size:

1. **Contiguity**: if the idle path's definitions are placed adjacent in the dictionary, does the loop's
   page count fall from 6 to 1–2?
2. **Pinning**: if one or two frames are pinned to those pages, does the idle loop reach **0 faults**?

This probe tests both on P24's own layer, changing **only the order of definitions** — not their content.

## Why it matters

If the idle loop can be made fault-free by layout alone, R3 survives on 4 frames and the OS layer can stay
as large as it is. If not, the layer itself must shrink (P26) — a different, harder change.

## Given — do not re-derive

* P24: layer = 80 definitions, 3044 B headerless, 5.9 frames; 10 defs/frame (3–15 spread);
  `POLL-EVENTS` 320 B; idle loop 6 pages / 6 faults/pass (864 µs); three-OS-word line 8 pages.
* Page fetch 144 µs (P16); dispatch 726 cycles (P20); 4 frames × 512 B.
* Harness and layer source: `probe/results/P24-os-layer/`.

## Method

1. Copy `probe/results/P24-os-layer/` into `probe/results/P25-hot-layout/`.
2. Instrument the fault path to record **which page** is touched per dispatch, and build the per-workload
   page-touch **histogram** for the idle loop (this is the data the reordering must improve).
3. **Reorder only.** Emit definitions so that the idle path is contiguous: event poll → event dispatch →
   task switch → sleep check, in that order, in one block. Report the new page histogram and page count.
4. **Pin.** With the reordered layer, pin the block containing the idle path to frames 0..k−1 and run:
   faults/pass must be measured for k = 1, 2 and 3 pinned frames.
5. Re-measure the other two workloads (three-OS-word line, compiling a definition) so a win on the idle
   loop is not a loss elsewhere.
6. Report the byte cost of the layout rule (padding/alignment), if any.

## Record

| Case | pages in idle loop | faults/pass | faults: 3-word line | faults: compile |
| --- | --- | --- | --- | --- |
| P24 baseline | 6 | 6 | 8 | 3 |
| reordered, 0 pinned | | | | |
| reordered, 1 pinned | | | | |
| reordered, 2 pinned | | | | |
| reordered, 3 pinned | | | | |

## Pass criteria

* reordering measured, with the page histogram before and after;
* at least one configuration reaching **0 faults/pass** on the idle loop;
* the other two workloads measured in the same configuration;
* byte cost of the rule stated.

## Failure criteria — and what each changes

* **Idle loop still ≥ 3 pages after reordering** ⇒ the loop's own code is too large or spread by control
  flow; layout cannot fix it. R3 then depends on P26's minimal layer.
* **Pinning 3 frames is needed** ⇒ only 1 frame is left for data, which is not viable; report it as such.
* **0 faults achieved only by pinning** ⇒ the design gains a permanent "pinned hot block" concept: state
  its size, its frames, and what happens when a task other than the idle loop needs those pages.
* **Reordering breaks a test** ⇒ report `FAIL` with the failing case; a layout rule that changes behaviour
  is a compiler bug.

## Doc deltas to hand back

* `docs/01-proposal.md` §6.1 — the layout rule and the measured faults/pass.
* `docs/01-proposal.md` §4.2 — a new rule if pinning becomes part of the design.
* `docs/01-proposal.md` §10 R3 — restated with measured faults.

## Do not

* Do not shrink or rewrite the OS layer — that is P26. This probe changes **order only**.
* Do not touch the board, `docs/`, or other probes' directories.
