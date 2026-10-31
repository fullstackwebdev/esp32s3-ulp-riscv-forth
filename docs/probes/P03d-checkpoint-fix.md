# P03d — Does moving the checkpoint after the fetch fix retry?

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P03b (sweep), P03c (cause proven) |
| Blocks | §4.2 rule 2 — the choice between fine-grained retry and word-boundary pinning |
| Serves | R5 |

## Question

With the checkpoint moved to **after** the token fetch and **before** execution, does the exhaustive
sweep become clean — 0 mismatches over every faultable dispatch position?

If yes, fine-grained retry works and word-boundary pinning is unnecessary. If no, the remaining
mismatches are a different cause and pinning becomes mandatory.

## Why this is the last cheap experiment

Word-boundary pinning collides with the measured budget: P01 gives **2 frames**, and P02 allows a
definition to span **2 pages**. Pinning a straddling definition would hold both frames for its whole
duration, so nested calls thrash. Fine-grained retry keeps frames transient — if it is correct, it is
the better machine.

## Given — do not re-derive

* P03b: 32 of 83 faultable positions mismatched at primitive granularity; baseline
  `err=OK disp=187 faults=15 sp=1 rsp=0 chk=4f99db40`.
* P03c: the cause is the checkpoint in the `VM_CKPT_NEXT` window, saved **before**
  `w = rd16(ip); ip += 2`. Specimen 61 re-runs `P_DOCOL` and pushes `1410` instead of `1488`.
  Cause (b) (store-before-fault inside one primitive) does not appear in that trace.
* `ERR_PAGE_FAULT_LOOP` already works (5 retries, `w=1430 ip=1432`), `ERR_RETRY_CAP` is the backstop.
* Harness: `probe/results/P03b-retry-progress/` **with P03c's window numbering fix** (distinct `p` per
  checkpoint site); reuse it, do not rewrite.

## Method

1. Copy P03b's harness into `probe/results/P03d-checkpoint-fix/` **and P03c's window-id fix with it** —
   without distinct `p` values the sweep numbers are unattributable.
2. Apply the single change: take the resume checkpoint **after** the token fetch
   (`w = rd16(ip); ip += 2`) and before execution, so a fault during that fetch re-fetches the same
   token instead of re-running the previous dispatch. Nothing else changes.
3. Baseline again (faults disabled): must reproduce `chk=4f99db40 sp=1 rsp=0`. If it does not, stop —
   `BLOCKED: baseline moved` — because you changed behaviour, not just the checkpoint.
4. Re-run the full sweep: one fault at each of the 187 dispatch positions, 4 frames, compare digests
   against the new baseline. Report positions tested, `no_access` count, mismatches with their
   `(w, ip, p)`.
5. If mismatches remain, take **one** of them and dump the 6 checkpoints around it in both runs — the
   same technique as P03c. One position, not a hunt.

## Record

| Item | Value |
| --- | --- |
| baseline digest | must equal `4f99db40` / `sp=1` / `rsp=0` |
| positions tested / `no_access` | n / n |
| **mismatches** | target **0** |
| remaining mismatch positions | list + one traced specimen if non-empty |
| hang | must be 0 |

## Pass criteria

* baseline unchanged, all positions tested, **0 mismatches**, no hangs.

## Failure criteria — and what each changes

* **0 mismatches** ⇒ adopt **fine-grained retry**: §4.2 rule 2 becomes the checkpoint-after-fetch rule
  with the measured evidence, word-boundary pinning is dropped, and the frame pressure disappears
  (frames become transient rather than held per call).
* **Mismatches remain** ⇒ the cause is not (only) the checkpoint. Word-boundary pinning becomes
  mandatory in §4.2, the compiler must emit per-definition page lists, and §4.3 must record that a
  straddling definition holds both frames (the thrash risk).
* **Baseline moved** ⇒ report `BLOCKED: baseline moved`; a changed baseline means the edit changed
  semantics and no sweep result is meaningful.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.2 rule 2 — either the fine-grained rule with the measured 0-mismatch sweep,
  or the pinning rule with the residual mismatch count.
* `docs/01-proposal.md` §10 R5 — the fault-retry item, restated with the measured position count.

## Do not

* Do not change anything except the checkpoint position. No other "while I'm here" edits.
* Do not touch the board, `docs/`, `probe/uforth/`, or other probes' directories.
