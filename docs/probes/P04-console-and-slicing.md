# P04 — Console, rings, and a sliced interpreter

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | — |
| Blocks | R2/R3 acceptance items about dropped bytes and non-blocking input |
| Serves | R2, R3 |

## Timebox — 15 minutes, one run, no slices

* **Hard cap: 15 minutes total**, from the first command to the written `RESULT.md`.
* **At T−2 minutes stop starting new work.** Wrap up, write `RESULT.md`, kill processes, kill the tmux
  session.
* **It all has to fit.** A cold ESP-IDF build is 2–3 minutes and a flash ~20 s, so if the probe needs
  a build, start it in the first five minutes — not at minute ten.
* **Every command carries `timeout`**: builds `timeout 300`, device ops `timeout 30`, host test runs
  `timeout 20`. No bare long-running command, no `&`, no `nohup`, no `/tmp`.
* **Every loop is bounded twice**: by iteration count *and* a wall-clock check inside the loop.
* **A hang is a `FAIL`**, with the exact command and the last output recorded.
* **If the question does not fit in 15 minutes, the question is too big.** Report what was measured;
  the orchestrator will cut a narrower question. Running the same probe again is not the answer, and
  splitting a probe into slices is not the answer either.

## Question

What ring depths and interpreter slice size *k* give a terminal that never drops a character and an
event loop that never stalls, for the worst realistic burst (a 100-line file pasted at once)?

## Why it matters

§8 claims connected mode at a 1–4 tick period with `drops_out == 0`, and §5 claims `interpret-step`
yields every *k* tokens. Both are numbers nobody has chosen. Pick them wrong and either the loop
stalls for a whole wake budget while compiling a line, or the output ring overflows and the terminal
silently eats part of an error message — the exact failure mode the repo forbids.

## Method

1. Copy `probe/uforth/` into `probe/results/P04-console-and-slicing/`.
2. Replace the blocking `forth_quit()` with a **sliced state machine**: `repl_step()` consumes at most
   `k` tokens, or until the line ends, or until it has consumed `n` characters from the command ring;
   returns one of `REPL_MORE / REPL_LINE_DONE / REPL_ERR`.
3. Drive it from a simulated scheduler tick: each "wake" calls `repl_step()` `W` times plus one
   simulated task. Simulate NUL-arrival from a ring of depth `C`; output into a ring of depth `O`.
4. Sweep `k ∈ {1, 4, 16, 64}`, `C ∈ {64, 128, 256}`, `O ∈ {128, 256}` against:
   - (a) one 60-character line typed at 10 chars/s;
   - (b) a 100-line `boot_min.fs`-sized file pasted at once;
   - (c) an interactive user alternating short lines with a long `: ... ;` definition.
   For each: tokens per step, worst-case steps to complete a line, dropped input bytes, dropped
   output bytes, and maximum "wake latency" (steps × simulated token cost) seen by the other task.
5. Derive the **requirement**: the smallest `(k, C, O)` that yields zero drops in (a)–(c) and a worst
   case latency under the 100 ms autonomous budget and the 30 µs connected budget (state which is
   binding).
6. Verify non-blocking `KEY`: with an empty ring it must return an error and consume nothing.

## Record

Sweep table (k × C × O × workload → drops in/out, worst latency, tokens/step), plus the recommended
triple and the reasoning, plus the measured bytes-per-token so the ULP budget can be projected.

## Pass criteria

* a `(k, C, O)` exists with **zero** drops in all three workloads;
* `KEY` with an empty ring consumes no step and returns a named error;
* the worst-case wake latency for the recommended triple is reported in both token-units and
  projected µs (using P05's cycles/tick once available — if P05 has not run, report token-units only
  and say so).

## Failure criteria — and what each changes

* **No triple gives zero drops within the RAM budget** (rings must fit in ~600 B) ⇒ §8's
  `drops_out == 0` acceptance item is unachievable as written; report the real bound and propose
  flow control (the host sends the next line only after the prompt byte) instead of a bigger ring.
* **`k` must be 1 to meet latency** ⇒ the interpreter state machine must be resumable at *every*
  token, which forces `run_from` to be the only execution path. Say so; it changes §5.
* **A 100-line paste takes more than one autonomous period** ⇒ acceptable, but the boot/paste story
  in §7 must state the expected duration rather than implying instant.

## Doc deltas to hand back

* `docs/01-proposal.md` §5 — the slice size and the "interpreter is sliced" paragraph, with the
  measured worst case.
* `docs/01-proposal.md` §8 — ring depths and the real drop bound.
* `docs/01-proposal.md` §10 — R2's "zero dropped bytes" item, restated with the measured bound if it
  cannot be zero.

## Do not

* Do not use a mock terminal that delivers characters instantly and in bulk; the point is to find the
  worst case.
* Do not touch the board or `docs/`.
