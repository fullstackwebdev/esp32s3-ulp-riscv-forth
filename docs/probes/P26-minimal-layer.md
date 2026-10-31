# P26 — What is the smallest OS layer that still satisfies R3 and R4?

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P24 (3044 B layer, 5.9 frames), P25 (layout) |
| Blocks | R3/R4 — the size the machine can actually afford |
| Serves | R3, R4 |

## Question

P24's layer is 3044 B headerless — 5.9 frames, more than the machine has. But that layer was written to
the *spirit* of the request, not to a byte budget. So: **how much machine does the requirement literally
need**, and does the minimal version fit in **two frames (1024 B)** with a fault-free idle loop?

R3 and R4 as written ask for: an event loop that never blocks and always retires; and several tasks that
take turns with their own stacks. That is much less than a full OS.

## Why it matters

If the minimal layer fits in 1024 B and the idle loop stays in two pages, the machine is real: R3 and R4
are met, and the remaining requirements (paging, console, storage) already have measured numbers. If even
the minimal layer does not fit, the honest conclusion is that the 8 KB machine cannot be a multitasking
Forth and the plan must choose which requirement to drop.

## Given — do not re-derive

* P24: tasks 1380 B / 39 defs, events 908 / 20, REPL 300 / 9, introspection 348 / 8, device 108 / 4.
  `POLL-EVENTS` alone is 320 B. 10 defs per 512 B frame.
* P13: stacks peak at 108 B; 3 tasks at 32 B records + 192 B of stacks each is 672 B of *dictionary*, not
  frames — the task records and stacks are data, and they compete with the dictionary, not the frames.
* P20: dispatch 726 cycles. P16: 144 µs per page fetch.
* 94 B of resident room. Frames 4 × 512 = 2048 B.

## Method

1. Copy `probe/results/P24-os-layer/` into `probe/results/P26-minimal-layer/`.
2. Write **the smallest layer that satisfies R3 and R4 as literally written** — no more. Suggested ceiling
   for each group, which you may renegotiate with a reason, not silently:
   - **tasks ≤ 300 B**: `TASK`, `YIELD`, `PAUSE` (shared with YIELD if possible), `SLEEP-TICKS`, the
     round-robin queue, and the 32 B record layout. Three tasks.
   - **events ≤ 250 B**: one ring, one `ON-EVENT` registration kind (GPIO pin), `POLL-EVENTS` written to fit
     one page.
   - **REPL ≤ 200 B**: line intake from the ring, `QUIT` as a task, prompt and error path.
   - **introspection ≤ 120 B**: `WORDS` and `.S` only (drop `?`).
   - **device ≤ 100 B**: `GPIO@`, `GPIO!` (drop `ADC@`, `MS` — they are not in R1–R8).
3. Compile it, measure per group headerless, and report the total against the 1024 B budget.
4. Measure the three workloads again: idle loop pages and faults/pass, three-OS-word line, compiling a
   definition.
5. State what was **dropped** from P24's layer and what each drop would have cost to keep — that table is
   the design decision, not a scorecard.

## Record

| Group | budget | actual | dropped from P24 |
| --- | --- | --- | --- |
| tasks | ≤ 300 | | |
| events | ≤ 250 | | |
| REPL | ≤ 200 | | |
| introspection | ≤ 120 | | |
| device | ≤ 100 | | |
| **total** | ≤ 1024 | | |

Plus: idle loop pages / faults per pass, and the other two workloads.

## Pass criteria

* the layer compiles and satisfies R3/R4's literal content (tasks take turns, the loop never blocks and
  always retires, events are dispatched);
* total headerless ≤ 1024 B, **or** a stated reason why a specific group could not meet its ceiling;
* idle loop pages and faults/pass measured.

## Failure criteria — and what each changes

* **Total > 1024 B with no defensible cut** ⇒ report the minimum achievable and the overrun. The design must
  then choose: more frames (out of the dictionary), fewer tasks, or a smaller prelude.
* **Idle loop still faults every pass at this size** ⇒ R3 is not achievable on 4 frames. That is the stop
  condition: the machine cannot be both multitasking and paged at this RAM, and the plan must say which
  requirement is dropped.
* **The layer compiles but the event ring needs more than one frame** ⇒ events must be data-only (a ring in
  dictionary/RTC memory), not code; state the split.

## Doc deltas to hand back

* `docs/01-proposal.md` §6.1 — replace P24's layer numbers with the minimal layer's, and record the drop
  table as the design decision.
* `docs/01-proposal.md` §10 R3/R4 — restated with the measured layer and faults.
* `docs/JOURNAL.md` — an entry naming what was given up and why.

## Do not

* Do not stub, empty or fake a definition to hit a ceiling. A missing word is a finding; a fake one is a lie.
* Do not change the primitive set.
* Do not touch the board, `docs/`, or other probes' directories.
