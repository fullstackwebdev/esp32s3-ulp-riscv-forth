# P03 — Paging model: retry, idempotency, frames, thrash detection

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P02 (token width), P04 (slicing granularity), `docs/01-proposal.md` §4.2 |
| Blocks | R5 acceptance, the resident page-table design |
| Serves | R5 (all checklist items), R6 (retry semantics) |

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

Does the fault → retire → retry model actually produce correct results for *every* fault position,
and how many frames are needed before a realistic workload stops thrashing?

## Why it matters

This is the riskiest part of the design. A page fault can interrupt a word at any token. If the
faulting primitive is not perfectly idempotent, the retry re-executes half a computation and the
result is wrong — silently, because there is no MMU to catch it. §4.2 rule 2 asserts it works; nothing
has proven it.

Doing this on the host, with a simulated byte server, costs nothing and can be exhaustive.

## Given (measured by earlier probes — do not re-derive)

* **P02:** with 32-bit xts a definition averages **39.2 B** (max 96 B), and **6.5–8.7 %** of
  definitions straddle a 512 B boundary. So §4.2 rule 1 is now **"a definition spans at most two
  pages; both pages are pinned while it runs"**, not "refuse a straddle". Your frame model must
  support pinning two frames to one definition at once — with 4 frames that leaves 2 for everything
  else, which is the configuration to test.
* **P04:** `k` tokens per step does **not** bound the work — one token calling a colon word with a
  100-iteration loop cost **505 primitive dispatches**. Therefore the resume point is a **primitive
  dispatch**, not a token: `run_from(w, ip, p)`. A fault may arrive at any `p`. Your injector must
  therefore enumerate primitive positions, not token positions.

## Method

1. Copy `probe/uforth/` into `probe/results/P03-paging-sim/`.
2. Implement, on the host build only:
   - a **frame table**: *N* frames of 512 B inside a fake address space where `0x1000_0000` is
     "PSRAM" (a flat `malloc`'d 1 MB) and `0x2000_0000` is "flash" (a flat file-backed region);
   - `@`/`!`/`C@`/`C!`/token-fetch routed through a `resolve(addr)` that either returns a resident
     pointer or raises `FAULT(addr)`;
   - a **retry protocol**: `run_from(w, ip, p)` returning `VM_RESUMED` or `VM_FAULT(addr)`, where `p`
     counts primitive dispatches inside the current token — the resume point measured to matter in
     P04. On fault the caller loads the frame from the fake server and re-enters the same `(w, ip, p)`;
   - a **fake server** with a configurable latency counter (it must *not* be instant: model the
     round trip as ≥ 1 token of simulated work, so ordering bugs surface).
3. **Exhaustive idempotency test.** Run a workload that touches 4 distinct pages; instrument the fault
   injector so that *every* possible (word, token-index) position faults exactly once across separate
   runs. For each run, compare the final stack and a checksum of all written pages against the
   no-fault run. Any mismatch is a data-integrity failure.
4. **Frame sweep.** With 2, 4, 8 frames, run: (a) the prelude compilation, (b) a synthetic loop
   touching 1 page, (c) a workload cycling through 3 pages, (d) a workload cycling through 12.
   Record faults, fault positions, and whether `ERR_HOT_SET` fires for (d) and stays clear for (a)–(c).
5. **Thrash definition.** Propose a concrete rule (e.g. `faults_per_wake > F` for *K* consecutive
   wakes) and show the numbers that justify the constants.
6. **LRU cost.** Measure instructions per `resolve()` on a resident hit and per fault, so the ULP
   budget question is at least bounded.

## Record

| Item | Value |
| --- | --- |
| fault positions tested | *n* |
| idempotency mismatches | *must be 0* |
| faults: prelude, 1-page, 3-page, 12-page workload | 4 tuples × 3 frame counts |
| `ERR_HOT_SET` fired where expected | yes/no per case |
| resolve() cost: hit / miss | instructions |
| proposed thrash rule and constants | text |

## Pass criteria

* zero idempotency mismatches across all fault positions;
* `ERR_HOT_SET` fires for the 12-page workload at 2 and 4 frames, and does not fire for the prelude;
* the fault path is re-entrant and leaves no partially-written cell (verify by checksum after each
  retry).

## Failure criteria — and what each changes

* **Any idempotency mismatch** ⇒ `FAIL`, highest priority. Report the exact faulting primitive with its
  `(word, token, primitive)` position. The fix is either "fault only at word boundaries" (a much simpler design: check
  residency on entry to `@`/`!`/token-fetch and make that check the fault point) or making the
  primitive restartable. `01-proposal.md` §4.2 rule 2 changes to whichever is true.
* **Prelude needs > 4 frames** ⇒ the resident dictionary must be smaller; raise the frame count and
  cut the dictionary, or pin the prelude permanently and page only user code.
* **`ERR_HOT_SET` cannot be made meaningful** ⇒ drop the detector rather than ship a lying counter,
  and say so in §4.2.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.2 — replace the retry description with the verified mechanism, and rule 3
  with the measured thrash rule and constants.
* `docs/01-proposal.md` §4.3 — replace the frame count if the data says 2 or 8.
* `docs/02-harness.md` — if the fault path needs a new mailbox field (e.g. a residency hint), add it.

## Do not

* Do not simplify the injector to "fault at word start only" — that is the assumption being tested.
* Do not treat a hang as a pass; a timeout is a `FAIL` with the position recorded.
* Do not touch the board or `docs/`.
