# P24 — Does the OS layer fit, and what does the paged hot set really look like?

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P22 (94 B spare), P13 (stacks), P16 (144 µs per fetch) |
| Blocks | R3 and R4 — whether tasks and the event loop can exist at all |
| Serves | R3, R4, R5 |

## Question

P22 left **94 bytes** of resident room after the prelude. R4 asks for tasks, an event loop, a REPL and
device words. So: **how big is the OS layer in dictionary bytes**, how much of it must be paged, and how
many definitions fit in one 512 B frame — i.e. what does the hot set look like when you are actually typing
at it?

## Why it matters

This is the question that decides whether "multi-threaded 8 KB operating system" is a description of the
machine or a wish. Every one of those words lives in paged storage and costs **144 µs** the first time it
is touched in a session. If the OS layer is 400 B, it is ~10 definitions and one frame holds it permanently.
If it is 3 KB, the working set exceeds the four frames and every interaction thrashes.

## Given — do not re-derive

* P22: resident dictionary 1104 B of `MEMSZ` 1188 (94 B spare); directory 812 B for 78 definitions;
  39.2 B/word with headers, ~28 B/word headerless at 32-bit (P02 ratio).
* P13: stacks peak at 108 B; compile depth scales with source nesting.
* P16: page fetch 144 µs (lower bound), 4 frames × 512 B.
* Prototype: `probe/uforth/` with the 40-primitive set from `probe/results/P20-native-accessors/`.

## Method

1. Copy P20's variant C tree into `probe/results/P24-os-layer/`.
2. Write the OS layer in Forth, as the design describes it, and compile it on the host against that
   primitive set. Keep it honest — no stubs, no empty definitions. Minimum content:
   - **tasks**: `TASK`, `YIELD`, `PAUSE`, `SLEEP-TICKS`, `STOP`, `TASKS`, plus the 32-byte record layout
     and a round-robin queue;
   - **events**: an event ring, `ON-GPIO`, `EMIT-EVENT`, `POLL-EVENTS`;
   - **REPL**: `QUIT` as a task, `KEY?`, `TYPE`, prompt and error reporting;
   - **introspection**: `WORDS`, `.S`, `?`;
   - **device words**: `GPIO@ GPIO! ADC@ MS`.
3. Compile with headers, then strip them, and report: **bytes with headers, bytes headerless, definitions
   count, bytes per definition** for the whole layer and for each group.
4. Compute: how many of these definitions fit in one 512 B frame, and what the working set is for
   (a) an idle event loop, (b) typing a line that calls three OS words, (c) compiling a new definition.
5. State whether the 94 B resident room can hold any of it, and if not, say what the first-call fault cost
   is for the most-used path (idle loop → event dispatch).

## Record

| Group | definitions | bytes with headers | headerless bytes |
| --- | --- | --- | --- |
| tasks | | | |
| events | | | |
| REPL | | | |
| introspection | | | |
| device words | | | |
| **total** | | | |

Plus: definitions per frame, and the three working sets with their fault counts.

## Pass criteria

* the layer **compiles** on the host against the shipped 40-primitive set (a layer that does not compile is
  not an answer);
* bytes measured both with and without headers;
* definitions-per-frame and the three working sets stated.

## Failure criteria — and what each changes

* **A working set needs more than 4 frames** ⇒ the hot set does not fit and every interaction faults.
  Either frames grow (dictionary shrinks) or the OS layer gets smaller; this is the §12 redesign trigger
  for R3/R4.
* **The layer does not compile against 40 primitives** ⇒ the trimmed set is too small; name the missing
  primitives and their cost, because P20's −824 B depends on that set.
* **Total layer < 512 B** ⇒ one frame holds it all, and the design note becomes "the OS layer is
  permanently resident in frame 0", which simplifies everything downstream.
* **Idle loop faults on every pass** ⇒ the event loop's own code is not cacheable, which is fatal for R3;
  report it plainly.

## Doc deltas to hand back

* `docs/01-proposal.md` §6 and §7 — the OS layer's measured size, the page it lives in, the working set.
* `docs/01-proposal.md` §10 R3/R4 — restated with the measured fault counts.
* `probe/EVIDENCE.md` — a new entry with the table.

## Do not

* Do not write empty definitions to make the count look right, and do not use words the primitive set does
  not have.
* Do not touch the board, `docs/`, or other probes' directories.
