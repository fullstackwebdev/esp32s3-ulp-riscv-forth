# TASK — Idea 1: table-driven binary primitives

Read `../SHARED_BRIEF.md` first. Goal: shrink `.text` **without removing or changing any primitive**.

## Why this is the best candidate
`vm_enter` is **2 782 B** of the 5 252 B `.text`, and it contains 64 primitive bodies at a measured **29.5 B**
each. Roughly 15–20 of those bodies are the same shape: pop two cells, compute, push one. A single kernel that
selects the operation from a table should replace ~450–590 B of bodies with ~120–150 B of kernel. Work out
whether that is true; measure it rather than believing it.

## Steps
1. Enumerate every two-operand/compare case in `src/uforth.c`, `src/p31_cases.inc`, `src/p33_cases.inc`.
   Classify each as **same-shape** or **shape-distinct** (needs carry/borrow, division, signed compare, memory
   access, control flow, `continue`/`return` in the body).
2. **Measure the constant first**: reshape ONE body into the kernel form and measure Δ`.text`. Do not refactor
   everything before you know the per-body number.
3. Then 5 words → 10 → every genuinely same-shape word. Report a measured Δ at each step.
4. Preserve the per-token checkpoint/state write in the dispatch loop. It is the resumability contract (P27):
   a variant that drops it is not a candidate, however small.
5. `tests/run.sh` must be green. If the suite does not cover an operation you touched, add `tests/<name>.fs` +
   `.expected` and **mutation-test** it (break the kernel on purpose, prove the test fails, restore).
6. State the cycle cost honestly: you **cannot** measure cycles on the host. State the dispatch effect and say
   that cycles are board-only.

## Deliverable
`FINDINGS.md`: classification table; variants table (`variant → Δ.text → Δ.rodata → suite`); measured cost per
body; projected total at full conversion **labelled ESTIMATE**; verdict; exact diff of the winner.
