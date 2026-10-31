# P21 — How much C stack does the engine actually use?

| | |
| --- | --- |
| Runs on | **host only** (compiler instrumentation, no execution needed) |
| Time box | **15 min**, one run, hard cap |
| Depends on | P12 (engine build), P14 (call structure) |
| Blocks | the 400 B C-stack line in §4.3 |
| Serves | R1, R5 |

## Question

§4.3 budgets **400 B for the C stack plus a guard band** — a guess. What is the deepest static call chain
in the engine, and what does it actually need? If it is 150 B, that is **250 B back to the dictionary**,
which is half the current shortfall.

## Why it matters

Every one of the five levers in §4.3 needs to be measured to be believed, and this is the cheapest: no
execution, no board, just the compiler's own frame accounting. The engine is not recursive, so the static
deepest chain is a *hard bound*, not an estimate.

## Given — do not re-derive

* P12's source tree: `probe/results/P12-engine-32bit/` (32-bit refs + paging), engine 3986 B.
* P14's call structure: `NEXT` → `rd32` → `rd16` → `rd8`; dispatch → primitive → `PUSH`/`POP`.
* The ULP's `sp` starts at `__stack_top` and grows down; `start.S` sets it and calls `main`.
* `-fstack-usage` is available in `riscv32-esp-elf-gcc 14.2.0`.

## Method

1. Copy P12's tree into `probe/results/P21-c-stack/`.
2. Rebuild the engine with `-fstack-usage` and collect the `.su` files (one line per function: frame
   size, static/dynamic, qualifiers). Report **every** function's frame size in a table.
3. Build the call graph (from `objdump -d`: who calls whom) and compute the **maximum chain sum** —
   the deepest path from `main` to a leaf. That is the hard bound; report the path and the sum.
4. Independently verify with a runtime check: on the host build, record the address of a local in `main`
   and in the deepest callee, and report the delta for each of the workloads P14 named (a primitive,
   a literal, a colon call, a branch, a page fault path).
5. Add the interrupt path: `ulp_riscv_vectors.S` saves registers on the same stack. Its frame must be
   added to the worst case **on top of** whatever the interpreter is doing when the interrupt lands.
   Report that number separately.
6. Recommend a C-stack size with a stated margin, and say what the margin is for.

## Record

| Item | Value |
| --- | --- |
| largest single frame | function, bytes |
| deepest chain | path, total bytes |
| measured host delta, main → deepest callee | bytes |
| interrupt frame (context save) | bytes |
| worst case incl. interrupt | bytes |
| recommended C stack + margin | bytes |

## Pass criteria

* every engine function's frame size listed, from the compiler's own `.su` output;
* the deepest chain named and summed, not guessed;
* the interrupt save added on top, with its source (`ulp_riscv_vectors.S` / the vector table);
* a recommended size with a stated margin and the reason for the margin.

## Failure criteria — and what each changes

* **Deepest chain + interrupt > 400 B** ⇒ the budget line is too small; report the real figure and what it
  costs the dictionary.
* **≤ 150 B** ⇒ §4.3's C stack drops to 256 B with a 100 B margin, returning **144 B** to the dictionary.
* **A frame is unbounded** (VLAs, `alloca`, or a large local array) ⇒ that is a defect in the engine to
  fix before any size claim; name the function.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.3 — the C-stack line with the measured chain and margin.
* `probe/EVIDENCE.md` — a short entry with the table.

## Do not

* Do not pad the measurement to make 400 look right; if it needs 420, say 420.
* Do not touch the board, `docs/`, or other probes' directories.
