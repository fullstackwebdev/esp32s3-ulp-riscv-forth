# P13 — How deep do the Forth stacks actually go?

| | |
| --- | --- |
| Runs on | host only (gcc, `-DSD=256`; no board, no `/dev/ttyACM*`) |
| Started | 2026-10-30T13:18:44−07:00 |
| Finished | 2026-10-30T13:22 (−07:00) — inside the 15 min box, one run, no PARTIAL |
| Verdict | **PASS** — the 400 B stack line holds. Peak **20 data + 7 return cells = 108 B**, on two *different* workloads. The compiler never exceeds **6 cells**, so it does **not** need its own stack for depth reasons. But the prototype's `SD = 16` is already too small for a plain interactive line and has no working overflow check. |

Files (all copies; `probe/uforth/` and `docs/` were not touched):

| File | What it is |
| --- | --- |
| `uforth.c` | copy of the baseline with two instrumented edits, both under `-DINSTRUMENT`/host only: (i) `hw_sp`/`hw_rsp` high-water marks sampled in `PUSH`/`RPUSH`, (ii) a `quiet_out` gate on `pl_emit` so `.`/`TYPE` output cannot land inside the results table |
| `p13_stack.c` | the workload driver: one window per row of the table, marks reset per workload |
| `boot_min.fs`, `host_test.c`, `probe_image.h` | unmodified copies of the baseline |
| `run.log` | the whole run, including the **per-line marks for all 74 prelude lines** |
| `build.log` | compiler output (`-Wall -Wextra`; the only two warnings are the dead `sp >= SD` check, see §2.4) |
| `tests.log` | the 58-test suite on the instrumented copy at `SD=256`: **57 PASS, 1 FAIL**, and the one failure is the test that asserts the `SD=16` wraparound defect, which cannot happen at 256 |

Build and run (exactly what was executed, each command under `timeout 30`):

```
gcc -DHOST -DINSTRUMENT -DSD=256 -DMEMSZ=16384 -std=c99 -Wall -Wextra -o p13_stack p13_stack.c
timeout 30 ./p13_stack > run.log 2>&1
gcc -DHOST -DINSTRUMENT -DSD=256 -std=c99 -Wall -Wextra -o uforth_test host_test.c
timeout 30 ./uforth_test > tests.log 2>&1
```

---

## 1. Answers

### 1.1 The table the brief asks for (cells, and bytes at 4 B/cell)

| Workload | max data cells | max return cells | bytes (data + return) | path |
| --- | --- | --- | --- | --- |
| (a) prelude compile (`boot_min.fs`, 74 lines, one window) | **3** | **2** | 12 + 8 = **20** | compile |
| (b) deepest single prelude definition (`: IF ['] 0BRANCH W, 0 W, HERE 2 - ; IMMEDIATE`) | **3** | **2** | 12 + 8 = **20** | compile |
| (b2) compile, 5-deep `IF` + 5-deep `DO` (nesting stress) | **6** | **2** | 24 + 8 = **32** | compile |
| (c) 3-level nested `DO … LOOP` with `I`/`J`, running | **2** | **7** | 8 + 28 = **36** | runtime |
| (d) string printing — `."` of 60 chars, and `TYPE` of 60 chars | **2** | **1** | 8 + 4 = **12** | runtime |
| (e) `find`/`number` worst case — 30-char token, 200-word dictionary | **1** | **0** | 4 + 0 = **4** | runtime |
| (f) interactive: a line of 20 numbers | **20** | **0** | 80 + 0 = **80** | runtime |
| (f) interactive: a line with a definition (`: SQ DUP * ;`) | **0** | **0** | **0** | compile |
| (4) 100-iteration loop, word → word → `100 0 DO … LOOP` | **2** | **4** | 8 + 16 = **24** | runtime |
| **peak** | **20** | **7** | **108** | — |

The two peaks are on **different** rows: the data peak is the interactive 20-number line, the return
peak is the 3-level nest. Taken as one simultaneous worst case (conservative) that is
**27 cells = 108 B**.

### 1.2 Peak with and without the compiler path

* **Peak over all workloads: 20 data + 7 return cells = 108 B.**
* **Peak excluding the compiler path: 20 data + 7 return cells = 108 B** — *identical*. The
  compile-time peak (6 + 2 = 8 cells including the 5-deep nesting stress; 3 + 2 = 5 cells for the
  prelude itself) is strictly below the runtime peak, so compilation never sets the budget.

That is the important shape of the result: **compile-time depth is a function of source nesting, not
of program size.** Compiling all 74 prelude lines costs the same 3 cells as compiling the single
deepest one, because `interpret()` drains the stack at every line end. Five nested `IF`s cost 5 cells
(one patch address per open `IF`, exactly as §7 says), five nested `DO`s cost 5 (one `HERE` per open
loop). Depth grows with *nesting depth*, which is a property of the source text, not of the workload.

### 1.3 Does the compiler need its own stack?

**No — not for depth.** Compile-time peak is 6 cells even with 5-deep nesting; the prelude needs 3.
A 32-cell separate compiler stack would be 8× more than the measured worst case and would buy nothing
in depth terms.

The reason a separate stack might still be wanted is *corruption*, not size: §7 notes the compiler
leaves patch addresses on the data stack, so a user word that runs in compile state (an immediate
word, `[']`-time code, or a buggy immediate) can disturb a pending patch address. That is a
correctness argument, and P13 cannot settle it — what P13 does settle is that if such a stack is
added, **8 cells is enough and 16 is generous**; a 32-cell array (§7's suggestion) is 128 B of the
resident budget spent on 2× margin over a 6-cell measurement.

### 1.4 Recommendation: cells per task, and does 400 B survive?

**400 B survives — but only if the per-task size is restated. §6's "32 cells data + 16 return
(192 B)" does not fit the 400 B line three times: 3 × 192 = 576 B.**

Measured, the whole interpreter plus the worst realistic workload needs **27 cells (108 B)**. So:

| | Current §6 | **P13 recommendation** | Why |
| --- | --- | --- | --- |
| data stack per task | 32 cells | **24 cells (96 B)** | measured peak 20 (a 20-number interactive line) + 4 cells margin; §6's 32 is not wrong, just unaffordable at 3 tasks |
| return stack per task | 16 cells | **8 cells (32 B)** | measured peak 7 (3-level nest = 6 + 1 colon frame) + 1 cell; a 4-level nest needs 9 |
| per task | 192 B | **128 B** | |
| three tasks | 576 B | **384 B** | fits the 400 B line with 16 B spare |

The interpreter does **not** need a stack of its own in addition to this: tasks are cooperative
(§6), so `interpret()` and `run()` always execute on the *running task's* stacks, and the 20-cell
interactive peak above is that path measured end to end.

Two consequences the orchestrator should decide on rather than inherit silently:

1. **8 return cells leaves exactly 1 cell of margin.** If 4-deep nesting must be *measured-safe*,
   the per-task figure becomes 24 + 12 = 144 B, three tasks = **432 B**, and the §4.3 stack line grows
   by 32 B — which comes out of the 1584 B resident dictionary and therefore out of resolution A's
   margin. P13's evidence is that 108 B is the real requirement, so the 400 B line is not the risk
   here; the *per-task split* is.
2. **Four tasks are not possible** at any sane split: 4 × 100 B = 25 cells per task, and the measured
   data peak alone is 20 cells before any return stack. §10 R4's "a fourth `TASK` fails with
   `ERR_TASK_NO_ROOM`" is therefore correct with real numbers behind it, and 3 tasks is the ceiling
   for a stack reason, not just a dictionary reason.

### 1.5 Two defects the measurement walked into

* **`SD = 16` cannot hold an interactive line.** Workload (f) pushes 20 cells from one line of
  twenty numbers; at the prototype's 16 cells the 17th push silently overwrites cell 0
  (`host_test.c` asserts exactly that behaviour today and it is one of the 58 tests). The prototype's
  stack is not merely small, it is below a one-line workload.
* **The overflow guard is dead code at any useful `SD`.** `sp` is `u8` and the check is
  `if (sp >= SD)`, so it can never fire for `SD > 255`; at `SD = 256` gcc reports
  `comparison is always false` (both occurrences, `build.log`). The shipped design must check depth
  *before* the store, with a wider type, or the "no wrapped stack" non-negotiable in §11 is unenforced.
  This is the same class as the existing `sp = 255` underflow defect.

---

## 2. Evidence

### 2.1 Method, and why it is not a capped measurement

`probe/uforth/uforth.c` was copied and built with `-DSD=256` so both stacks are 256 cells (1024 B)
each — 10× the largest measured mark. Every row prints the marks; the program also prints the bound
(`SD bound per stack = 256 cells`) next to the peak, so a capped result would be visible as a mark
equal to 256. **No mark anywhere in `run.log` is 256; the largest is 20.**

High-water sampling: `sp` only ever grows inside `PUSH` and `rsp` only inside `RPUSH` (every other
site — `DROP`, `POP`, `RPOP`, the `rsp -= 2` in `(LOOP)`/`UNLOOP` — only decreases), so those two are
the complete set of sample points. `mark()` resets the marks *and* `sp`/`rsp` before each workload, so
no row inherits a previous row's floor.

### 2.2 Per-workload detail from `run.log`

```
(a) prelude compile          |    3 |    2 |    20 | compile      HERE=1350 after the prelude
(b) deepest single definition|    3 |    2 |    20 | compile  <- : IF  ['] 0BRANCH W, 0 W, HERE 2 - ; IMMEDIATE
(b2) compile 5-deep IF+DO    |    6 |    2 |    32 | compile
(c) 3-level nested loops     |    2 |    7 |    36 | runtime
    (c) compile of the same 3-deep word: ds=4 rs=2 (run was ds=2 rs=7)
(d) string printing          |    2 |    1 |    12 | runtime
(e) find/number worst case   |    1 |    0 |     4 | runtime
(f) interactive: 20 numbers  |   20 |    0 |    80 | runtime
(f) interactive: definition  |    0 |    0 |     0 | compile
(4) 100-iteration loop       |    2 |    4 |    24 | runtime
  control: 1 iteration ds=2 rs=4  vs 100 iterations ds=2 rs=4
  depth at iteration 100 == depth at iteration 1: no per-iteration growth
-----------------------------------------------------------------
PEAK over all workloads      |   20 |    7 |   108 | fits 100 cells
PEAK excluding compiler      |   20 |    7 |   108 | fits 100 cells
```

Notes on individual rows:

* **(a) vs (b):** the whole-file window and the per-line maximum are the same 3/2. `run.log` prints
  all 74 per-line marks; only the eleven immediate control words (`IF/THEN/ELSE/BEGIN/UNTIL/AGAIN/
  WHILE/REPEAT/DO/LOOP/+LOOP`, and `?DUP` at 2/2) have non-zero marks at all, and they are all 3/2
  or less. Every plain definition (`: 2DUP OVER OVER ;`, `: */ SWAP ROT * SWAP / ;`, …) is 0/0 —
  compiling a colon definition in this engine touches no stack.
* **(c) 7 return cells** = 1 colon frame (`N3`) + 3 × 2 loop cells (limit + index), and it is the
  deepest return stack in the whole probe. The compile of the *same* word peaks at 4 data cells (one
  `HERE` per open `DO`), which is why compile and runtime get separate windows.
* **(d)** is 2 cells, not 60: `."` emits characters straight from the compiled string via `(.")`
  and `TYPE` pops its two arguments (address, count). String *length* costs nothing on either stack.
* **(e)** is the row that falsifies the P04-driven worry. A 30-character token scanned against 200
  thirty-character headers, plus a 30-digit number, costs **1 data cell and 0 return cells**: `find()`
  and `number()` are C loops with hoisted locals, not Forth recursion. The 505 dispatches cost time,
  not stack.
* **(4)** is P04's case, and the control proves the point of the brief: 1 iteration and 100
  iterations have *the same* marks (2 data, 4 return), so the 100th iteration is not deeper than the
  first. The loop frame is pushed once by `(DO)` and popped by `(LOOP)` — it does not grow per pass.
* The 20-cell interactive peak is the only row driven by *user input volume*; it is also the row that
  sets the per-task data-stack size.

### 2.3 The 58-test suite still passes (with one expected exception)

`tests.log`: **57 PASS, 1 FAIL**. The failure is

```
FAIL  DEFECT: cell 0 was overwritten by the 17th push   got 0x00000001 (1), want 0x00000011 (17)
```

which is the test asserting the `SD = 16` wraparound. At `SD = 256` there is no 17th-push aliasing to
assert, so the test is inapplicable rather than broken. Every other test — including the
`push 20 into a 16-deep stack` case, which still passes because it only checks the post-condition
`sp == 20` and no error — behaves identically, which is the evidence that the instrumentation changed
no behaviour.

### 2.4 Build warnings, both of them meaningful

```
uforth.c:331:16: warning: comparison is always false due to limited range of data type [-Wtype-limits]
uforth.c:391:16: warning: comparison is always false due to limited range of data type [-Wtype-limits]
```

`if (sp >= SD)` with `u8 sp` and `SD = 256`. This is §1.5's second defect, surfaced by the probe's own
`-DSD=256`.

### 2.5 What would have made this measurement worthless, and was avoided

* Leaving `SD` at 16: every mark would have been ≤ 16 and the table would have been a description of
  the array, not of the workload. The interactive row alone (20 cells) proves it.
* Measuring "compile + run" in one window: the 3-deep nest would have been reported as 4 data cells
  (the compile) instead of 2 (the run), and the compile peak as 4 instead of its own 4/2.
* Letting the Forth program print into the table: the first run lost the entire `(d)` row inside 60
  characters of `."` output. Hence `quiet_out`.
* Trusting `sp` without resetting it per workload: an early version of (c) left 27 cells on the stack
  (its body popped one less than it pushed) and (d) then reported 29 as its own floor.

---

## 3. Verdict

**PASS.** The question was whether 400 B for both stacks is a guess that could be wrong by 2×. It is
not: the measured peak is **108 B (20 data + 7 return cells)**, worst case across a prelude compile, a
3-level nested loop, 60-character string printing, a 200-word `find` plus a 30-digit `number`, a
20-number interactive line, and P04's 100-iteration loop. That is **3.7× headroom in the 400 B line**.

Against the brief's pass criteria:

* a table from instrumented runs with the marks as numbers — **yes**, §1.1, from `run.log`;
* the peak stated with and without the compiler path — **yes**, §1.2, and they are equal (108 B);
* a recommendation of cells per task plus whether 400 B survives — **yes**, §1.4: **24 data + 8
  return = 128 B per task, three tasks = 384 B, so 400 B survives**; §6's 192 B/task does not.

Against the brief's failure criteria:

* *peak > 100 cells* — **not triggered** (27 cells, or 108 B; the numbers coincide only by accident,
  since the brief's 100 cells = 400 B and the peak is 27 cells = 108 B).
* *compile-time peak ≫ runtime peak* — **not triggered, and the opposite**: compile-time is 6 cells
  vs runtime 20. A separate compiler stack is **not** justified by depth. If one is added later for
  the §7 corruption reason, 8 cells is enough.
* *nesting is shallow everywhere (< 32 cells)* — **triggered**. Depth is shallow: max 7 return cells,
  max 20 data cells, and the 20 is not nesting at all — it is twenty numbers on one line. So §6's
  per-task stack **can** be halved (192 → 128 B), which is what makes three tasks fit inside 400 B.

The qualification, which belongs in §11 rather than in the stack line: the peaks are shallow but the
**overflow guard does not exist** (§1.5). A 24-cell data stack that cannot detect its 25th push is
worse than a 32-cell one, because a real user pushing 25 numbers gets a wrapped `sp` and plausible
wrong answers — the exact non-negotiable in §11. The depth budget is settled; the trap is not.

---

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §4.3 — the stack line

Replace the row

```
| Forth stacks (data + return) | 400 | 400 |
```

with

```
| Forth stacks (data + return) | 400 | **400** (measured peak 108 B: 20 data + 7 return cells; 3 tasks × 128 B) |
```

and add, immediately after the §4.3 table's "Measured side facts (P01)" paragraph:

```
Measured side facts (P13): the peak depth over a prelude compile, a 3-level nested `DO … LOOP`, 60-character
`."`/`TYPE`, a 30-character `find` against 200 headers plus a 30-digit `number`, a 20-number interactive line
and a 100-iteration loop is **20 data + 7 return cells = 108 B**; the compile-time peak is **6 cells** even with
5-deep `IF`/`DO` nesting, i.e. below the runtime peak, so compilation does not size the stacks. Depth scales
with *nesting depth*, not with program size: `interpret()` drains the stack at every line end, so compiling all
74 lines of the prelude costs the same 3 cells as compiling its deepest single definition. The prototype's
`SD = 16` is below a single 20-number interactive line, and its `if (sp >= SD)` guard is dead code for
`SD > 255` because `sp` is `u8` — depth must be checked before the store, or §11's "no wrapped stack" is
unenforced.
```

### 4.2 `docs/01-proposal.md` §6 — cells per task, or the separate compiler stack

Replace the sentence

```
Stacks are allocated per task out of the dictionary at `TASK` time; the recommended size is 32 cells
data + 16 return (192 B), which makes **three tasks** the realistic ceiling. `ERR_TASK_NO_ROOM` is a
named failure, not a clamp.
```

with

```
Stacks are allocated per task out of the dictionary at `TASK` time; the measured size is **24 cells data
(96 B) + 8 cells return (32 B) = 128 B per task** (P13: peak 20 data cells on a 20-number interactive line,
7 return cells on a 3-level nest), which makes **three tasks** fit in the 400 B line at 384 B with 16 B spare,
and makes a fourth impossible on stack grounds alone (4 × 100 B = 25 cells each, below the 20-cell data peak
plus any return stack). `ERR_TASK_NO_ROOM` is a named failure, not a clamp. If 4-deep nesting must be
measured-safe, the return stack grows to 12 cells and the per-task cost to 144 B (three tasks = 432 B, +32 B
against §4.3). Cooperative switching means the interpreter runs on the *running task's* stacks, so there is no
separate interpreter stack; the compiler does not need one either at 6 cells of measured depth, though a
separate 8-cell compiler stack remains an option for the §7 patch-address corruption, not for depth.
```

### 4.3 `docs/01-proposal.md` §10 R4 — the "three tasks" item

Replace

```
- [ ] Three tasks each increment their own counter; after 1000 wakes the three counters differ by
      at most 1 and the sum equals the expected total for the quantum in use.
```

with

```
- [ ] Three tasks each increment their own counter; after 1000 wakes the three counters differ by
      at most 1 and the sum equals the expected total for the quantum in use.
- [ ] Three tasks of **24 data + 8 return cells each (128 B, 384 B total)** are allocated from the
      dictionary and all three run; the measured peak demand per task is 20 data + 7 return cells (P13),
      so each task keeps at least 1 cell of return-stack margin and 4 of data-stack margin.
- [ ] A 4-level `DO … LOOP` nest (9 return cells) **overflows** an 8-cell return stack and raises a named
      error; it is not silently wrapped. This is the case that decides 8 cells vs 12.
```

---

## 5. Follow-ups

1. **P13a — stack overflow must be a named error, not a wrap.** The only real risk P13 found. Make
   `sp`/`rsp` wide enough that `sp >= SD` can be true, check *before* the store in `PUSH`/`RPUSH`, and
   add an `ERR_STACK_OVERFLOW` in the style of P04's `ERR_LINE_LONG`. Cost: two comparisons per push;
   no bytes. Without it the 24-cell recommendation is a budget for a stack that cannot defend itself.
2. **Decide 8 vs 12 return cells per task** (§1.4 item 1). It is a 32 B decision against the 1584 B
   dictionary and it changes §4.3 by 8 %. The measured requirement is 7; the choice is how much
   nesting beyond 3 levels the design promises.
3. **The separate compiler stack is a correctness question, not a depth one.** If §7's patch-address
   corruption is real, size it at 8 cells; the 32-cell suggestion is 4× the measured worst case.
   Someone should write the failing case (an immediate word that runs while an `IF` patch address is
   pending) before spending the bytes.
4. **Re-measure after the resident dictionary is restructured (resolution A).** Depth is a property of
   `run()`/`interpret()`, which resolution A does not change, so the 108 B figure should survive — but
   headerless words change `find()`'s inner loop, and row (e) is the one that depends on it (it cost
   0 cells either way).
