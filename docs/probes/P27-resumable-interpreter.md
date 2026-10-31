# P27 — Make the interpreter resumable, and prove tasks really switch

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P03d (checkpoint-after-fetch), P26 (minimal layer) |
| Blocks | R3, R4 — and paging, which needs the same resume machinery |
| Serves | R3, R4, R5 |

## Question

P26 measured the scheduler's *books*: 22 definitions, 1024 B, task records that rotate. But `dsp`, `rsp` and
`ip` are still C statics of `run()`, so **the machine does not actually switch — only the accounting does.**
Does a real context switch work: save the entire interpreter state at `PAUSE`, restore another task's, and
continue as if nothing happened — including when `PAUSE` is called from inside a colon word?

## Why it matters

This is the last structural change before anything can run on the chip. The same machinery is what paging
needs (resume at an arbitrary dispatch), and it is what R3 and R4 both depend on. If it does not work, the
"multi-threaded 8 KB OS" is a data structure, not a machine.

## Given — do not re-derive

* P03d: the resume point is a **primitive dispatch**, checkpointed **after** the token fetch and before
  execution. 0 mismatches over 187 positions.
* P26: the layer, its task record (32 B), and the finding that records rotate but state does not.
* P13: stacks peak at 20 data + 7 return cells; 3 tasks at 192 B of stacks each.
* Prototype: `probe/uforth/`, 58 tests; 40-primitive set from `probe/results/P20-native-accessors/`.

## Method

1. Copy the prototype into `probe/results/P27-resumable/`.
2. Make the interpreter state explicit. Minimum content of a switch point:
   `ip`, `w`, `p` (dispatch position), the two stack pointers, and whatever `run()` keeps live across a
   dispatch that is not already in memory. Document the list.
3. Implement `PAUSE` as: save current, pick next ready, restore, continue **without unwinding the C stack**.
   That is the hard part — a `PAUSE` inside a colon word must return into the middle of that word on
   resume, not to its caller.
4. Prove it three ways, each with an independently predicted answer (compute the expectation on the host,
   do not eyeball it):
   - **(a) interleaving**: three tasks incrementing counters with a fixed quantum, run to completion. The
     per-task counts and the global order must match a prediction computed outside the VM.
   - **(b) suspend mid-word**: a task that is `PAUSE`d in the middle of a colon word, resumed once, must
     produce byte-identical results and stacks to the same word run without a `PAUSE`.
   - **(c) nested**: a `PAUSE` inside a `DO` loop inside a colon word, resumed several times across the loop.
5. Repeat (b) and (c) with a **page fault** injected at the same position instead of a `PAUSE` — the two
   mechanisms must be the same code path, and if they are not, say so.
6. Keep the 58-test suite green.

## Record

| Test | predicted | actual | verdict |
| --- | --- | --- | --- |
| (a) three-task interleaving | | | |
| (b) suspend mid-word | | | |
| (c) suspend inside DO inside a word | | | |
| (d) page fault at the same positions | | | |
| suite | 58/58 | | |

## Pass criteria

* (a)–(c) match independently computed expectations exactly;
* the page-fault path and the `PAUSE` path share one resume mechanism (say where);
* the 58-test suite still passes.

## Failure criteria — and what each changes

* **`PAUSE` works only between words** ⇒ the quantum must be word-granular, and a long word cannot be
  pre-empted. That is acceptable but must be stated, and §5's dispatch budget becomes a warning rather than
  a switch.
* **`PAUSE` inside a word corrupts the C stack** ⇒ the interpreter must not use the C stack for its own
  control flow at all (a threaded interpreter with an explicit return stack). That is a significant rewrite —
  report it before doing it.
* **The page-fault path differs from the `PAUSE` path** ⇒ two resume mechanisms means two sets of bugs; unify
  them or justify the split in writing.
* **Any test regression** ⇒ `FAIL`.

## Doc deltas to hand back

* `docs/01-proposal.md` §6 — the VM state that a switch saves, verified; and the quantum's granularity.
* `docs/01-proposal.md` §5 — whether a long word can be pre-empted.
* `docs/01-proposal.md` §10 R3/R4 — restated with what was proven.

## Do not

* Do not fake the switch by saving only the stack pointers and re-entering at `w`.
* Do not compute the expected interleaving from the VM's own output.
* Do not touch the board, `docs/`, or other probes' directories.
