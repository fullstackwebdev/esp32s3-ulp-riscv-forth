# P13 — How deep do the Forth stacks actually go?

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P04 (505-dispatch token) |
| Blocks | the 400-byte stack line in §4.3; the per-task stack size in §6 |
| Serves | R4, R5 |

## Question

The design budgets **400 B for both Forth stacks** (100 cells total). P04 found that one token can run
505 primitive dispatches, which implies real nesting — `find`, `number`, `."`, nested definitions,
`DO … LOOP` frames. What is the **maximum observed depth** of the data stack and of the return stack
across the prelude and realistic programs, and how much headroom does 400 B actually leave?

## Why it matters

Stack depth is the one budget line that is pure guess. If the prelude peaks at 40 cells but a nested
definition with loops and string printing peaks at 90, then a single task plus the interpreter already
eats the whole 400 B before any user word runs — and §6's "three tasks, 192 B each" is fiction.

## Given — do not re-derive

* Host prototype + boot layer: `probe/uforth/` (`uforth.c`, `boot_min.fs`, `host_test.c`, 58 tests).
* Stacks are `u32 ds[SD]` / `rs[SD]` with `SD = 16` in the prototype — **raise `SD` for this probe**,
  otherwise the measurement is capped by the thing being measured. Use `-DSD=256`.
* P04's finding: a token calling a word with a 100-iteration loop costs 505 dispatches; the interpreter
  must survive that.

## Method

1. Copy `probe/uforth/` to `probe/results/P13-stack-depth/`, build with `-DSD=256`.
2. Instrument: wrap `PUSH`, `POP`, `RPUSH`, `RPOP` (or the macros) to record `sp` and `rsp` high-water
   marks; reset the marks per workload; print `max_sp`, `max_rsp` at the end.
3. Run each workload separately and report a row each (max data cells, max return cells):
   - (a) compiling the prelude (`boot_min.fs`);
   - (b) the deepest **single definition** in the prelude (e.g. `: */ SWAP ROT * SWAP / ;` vs the
     control words) — measure each definition compiled alone;
   - (c) nested `DO … LOOP` with `I` and `J` inside a colon word, 3 levels;
   - (d) a definition that uses `."` and `TYPE` with a 60-character string;
   - (e) `find` + `number` worst case: a 30-character token looked up in a 200-word dictionary;
   - (f) the interactive path: `interpret()` on a line with 20 numbers, then a line with a definition.
4. Add **one** deep case the design actually allows: a word that calls a word that runs a `100 0 DO`
   loop containing `I .`-style work (no `.` yet — use `I` and `DUP`), and report depth at the 100th
   iteration. This is the case P04 measured.
5. State the requirement two ways: **peak over all workloads**, and **peak excluding the compiler**
   (runtime budget for a task is different from compile-time budget).

## Record

| Workload | max data cells | max return cells | bytes at 4 B/cell |
| --- | --- | --- | --- |
| prelude compile | | | |
| deepest prelude definition | | | |
| 3-level nested loops | | | |
| string printing | | | |
| `find`/`number` worst case | | | |
| interactive line | | | |
| 100-iteration loop | | | |
| **peak** | | | |

## Pass criteria

* a table produced from instrumented runs, with the high-water marks as numbers;
* the peak stated both with and without the compiler path;
* a recommendation: cells per task, and whether 400 B total survives.

## Failure criteria — and what each changes

* **Peak > 100 cells (400 B)** ⇒ §4.3's stack line is too small. Report the real figure and which
  workload sets it; the dictionary loses the difference, which may push resolution A back over.
* **Compile-time peak ≫ runtime peak** ⇒ the compiler needs its **own** small stack (a separate 32-cell
  array) rather than borrowing the data stack. That is a design change worth making deliberately: §7
  points out the compiler already leaves patch addresses on the data stack.
* **Nesting is shallow everywhere (< 32 cells)** ⇒ report the headroom, because it means the per-task
  stack in §6 can be halved and a fourth task becomes possible.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.3 — the stack line, with the measured peak.
* `docs/01-proposal.md` §6 — cells per task, or the separate compiler stack.
* `docs/01-proposal.md` §10 R4 — the "three tasks" item, restated with real stack sizes.

## Do not

* Do not raise `SD` and then report depths equal to `SD` — that is a capped measurement, not a result.
* Do not touch the board, `docs/`, or other probes' directories.
