# P28 — Paying for R4: does the budget close with task state in it?

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P22 (linked machine, 94 B spare), P27 (140 B/task) |
| Blocks | R4 — whether the machine can run more than one task at all |
| Serves | R3, R4 |

## Question

P22 linked a machine with **94 B** spare. P27 then measured that a real context switch needs **140 B per
task** (both stacks saved by value), so three tasks need **420 B** and two need **280 B**. Does any
combination of the measured levers close that gap — and which is cheapest in what it gives up?

## Why it matters

This is the last budget question. Everything else is measured and fits; R4 is the one requirement with a
negative balance. If no combination closes, the machine cannot multitask and the plan must say so.

## Given — do not re-derive

* P22: engine 3190, frames 2048, VM+table 400, Forth stacks 128, rings 600, C stack 320, hooks 142,
  `MEMSZ` 1188, resident dictionary 1104, **94 B left**.
* P27: **136 B of VM state + 4 B record = 140 B/task** at `SD=16`; **268 B/task** at `SD=32`.
* P26: minimal OS layer 1024 B headerless, of which **40 B is data** (`SLOTS` + `RING`), stored in the
  dictionary, not the frames.
* P13: single-task stack peak is 20 data + 7 return cells — so `SD=16` is tight but was used by P27.
* P02: 16-bit code tokens cost 1/1.49 of the 32-bit dictionary, and the engine barely changes (P12: width
  itself was ~free; +168 was paging).
* P25: page claims need a tracer; do not reason about paging from placement.

## Method

Compute, do not estimate. For each combination below, report the resulting resident dictionary, the gap to
the prelude's resident need, and what it costs functionally:

| # | Combination |
| --- | --- |
| A | as linked, **1 task** (baseline) |
| B | **2 tasks** at `SD=16` |
| C | **3 tasks** at `SD=16` |
| D | 3 tasks + **16-bit code tokens** |
| E | 3 tasks + 16-bit tokens + **cold prelude words moved to paged storage** (name the words and their bytes) |
| F | 3 tasks + 16-bit tokens + **`SD=12`** stacks (is 12 enough? use P13's 27-cell peak as the constraint) |

For D and E, the 16-bit build is the one measured in P02 — reuse it rather than re-deriving the ratio.
For F, state whether 12 cells is defensible given P13's peak, or reject it. **Two frames cannot be shaved:**
P03f/P19 established 4 × 512 B as the minimum that boots.

Deliver a table with, for each combination: `MEMSZ` available, resident need, **gap**, tasks supported, and
what it gives up (words, width, headroom).

## Record

| # | tasks | MEMSZ available | resident need | gap | gives up |
| --- | --- | --- | --- | --- | --- |
| A | 1 | | | | |
| B | 2 | | | | |
| C | 3 | | | | |
| D | 3 + 16-bit | | | | |
| E | 3 + 16-bit + paged prelude | | | | |
| F | 3 + 16-bit + `SD=12` | | | | |

## Pass criteria

* every combination computed from the measured numbers, with the arithmetic shown;
* at least one row stating a **positive** gap or an explicit "none closes";
* the functional cost of each closing row named (which words, which width, how much headroom).

## Failure criteria — and what each changes

* **No combination closes** ⇒ R4 is dropped or reduced to two tasks. That is a scope decision for the
  operator, not a probe result to absorb silently. Report it as the headline.
* **Only 16-bit closes** ⇒ adopt 16-bit code tokens, restoring the 64 KB code ceiling — and note that R5
  is unaffected because data addresses were always 32-bit.
* **Only "paged prelude" closes** ⇒ the resident set becomes "engine + task state + hot words", and the
  first REPL interaction after boot pays faults for the rest. State the expected fault count with a tracer-
  based number if one exists, otherwise say it must be measured.
* **`SD=12` looks necessary** ⇒ check it against P13's 27-cell peak before proposing it; 12 cells is less
  than the measured peak and is therefore not viable unless the peak changes.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.3 — the closing table, or the statement that R4 does not close.
* `docs/01-proposal.md` §10 R4 — restated with the task count the machine can actually support.
* `docs/JOURNAL.md` — the decision and what it cost.

## Do not

* Do not shave frames, the C stack, or the rings without saying which measured margin you are spending.
* Do not touch the board, `docs/`, or other probes' directories.
