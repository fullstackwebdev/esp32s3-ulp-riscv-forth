# P03b — Retry progress: does every fault position converge?

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P03 (harness), P02 |
| Blocks | R5 acceptance, the `run_from(w, ip, p)` retry contract |
| Serves | R5, open question Q-retry |

## Question

One thing only: for a single fixed 200-dispatch workload at **4 frames**, does re-entering
`(w, ip, p)` after a page fetch produce the same result as the fault-free run at **every** dispatch
position — and does a progress bound turn a non-converging retry into a named error instead of a hang?

P03 could not answer this: its own fixture corrupted the dictionary (see "Given"), so the measurement
never ran.

## Given — do not re-derive, and do not re-discover

* **P03 built the harness** at `probe/results/P03-paging-sim/` (`paging_sim.c`, 24 KB): frame table,
  `resolve()`, fault injection, per-workload runner, `RESULT.md`. **Start from that code**, copy it
  into `probe/results/P03b-retry-progress/`, fix it, and use it. Do not write a new simulator.
* **Your blockers, from P03's write-up:**
  - the baseline digest returned `err=99` because the workload source used `HEX`, and `HEX` was
    broken: `: BASE 12 @ ;` returned the *contents* of `V_BASE`, so `HEX` wrote 16 into
    `V_LATEST+2` and destroyed the dictionary chain. **Fixed in `probe/uforth/boot_min.fs`** — `BASE`
    now pushes the address `12`. Copy the fixed file.
  - a hang at 4 frames in the `W1` workload, position not captured, suspected retry livelock.
  - `resolve()` was measured in host nanoseconds; the instruction count was cut. **Do not measure
    timing.** This probe is about correctness, not speed.
* **P04 says the resume point is a primitive dispatch**, so enumerate dispatch positions, not token
  positions.

## Method

1. Copy P03's harness; replace its `boot_min.fs` with the fixed one from `probe/uforth/`.
2. **Baseline first**: run the workload with fault injection disabled and record a digest of the
   final stacks + every touched page. If `err != 0` here, stop and report `BLOCKED: baseline broken`
   with the digest — do not proceed to the sweep on a broken baseline. This is the exact failure P03
   hit.
3. Fix P03's diagnostics before sweeping: print `(w, ip, p, addr, retry_count)` on **every** fault,
   to a log file, not to stdout through `head`.
4. Add the **progress bound**: a retry that returns to the same `(w, ip, p)` twice without an
   intervening successful dispatch must abort with `ERR_PAGE_FAULT_LOOP`. Prove it fires by
   injecting a permanent fault at a fixed position and confirming the named error instead of a hang.
5. Sweep: for each dispatch position `p = 1 … N`, run once with a fault injected exactly at `p`,
   compare the digest against the baseline. Record: positions tested, positions skipped, mismatches
   with their `(w, ip, p)`.
6. Frame count stays at 4. Do not sweep frames, do not test other workloads, do not measure time.

## Record

| Item | Value |
| --- | --- |
| baseline digest valid | yes/no |
| dispatch positions in the workload | N |
| positions tested | n (must equal N) |
| mismatches | **must be 0** |
| `ERR_PAGE_FAULT_LOOP` fires on a permanent fault | yes/no |
| hangs | must be 0; any hang is a `FAIL` with `(w, ip, p)` |

## Pass criteria

* baseline clean, every position tested, **zero mismatches**, no hangs;
* the progress bound converts a permanent fault into `ERR_PAGE_FAULT_LOOP` rather than a stall.

## Failure criteria — and what each changes

* **Any mismatch** ⇒ `FAIL`, and the architecture changes: the resume point moves to word boundaries
  (check residency at the top of each word, fault only there). Report the position; do not attempt a
  fix.
* **A hang survives the progress bound** ⇒ the fault is being re-raised on a *different* `p` than the
  one that retired. Report the sequence; the retry contract needs the position stored, not recomputed.
* **`ERR_PAGE_FAULT_LOOP` never fires** ⇒ the bound is not detecting what it claims; fix it before
  reporting a pass.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.2 rule 2 — replace the retry description with the verified mechanism and
  add the progress bound if it is needed.
* `docs/01-proposal.md` §10 R5 — the fault-retry item, restated with the measured position count.

## Do not

* Do not re-run P03's whole matrix; this probe answers one thing.
* Do not edit `docs/` or `probe/uforth/uforth.c`.
* Do not pipe a long run through `head`; log to a file.
