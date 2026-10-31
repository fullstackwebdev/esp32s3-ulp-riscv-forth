# P03c — One position, two traces: confirm the retry mechanism

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P03b (harness, position 61) |
| Blocks | §4.2 rule 2 — word-boundary pinning is the fix, but this confirms *why* |
| Serves | R5 |

## Question

At P03b's specimen position (61: `BUMP`, `w=234`, fault at `ip=1520`, one retry, no cascade), what
exactly does the retried run do differently from the fault-free run — and is the cause (a) a
checkpoint taken **before** the token fetch, so a completed dispatch is re-executed, or (b) a store
executed early in a primitive that faults later in the same dispatch?

One position. Two traces. Diff them.

## Given — from P03b, do not re-derive

* Harness: `probe/results/P03b-retry-progress/` (reuse it; copy into your own directory).
* Baseline: `err=OK disp=187 faults=15 sp=1 rsp=0 chk=4f99db40`.
* Position 61 mismatches with **one** fault and **one** retry — the cleanest specimen in the sweep.
* 32 of 83 faultable positions mismatch; do not re-sweep, do not test other positions.
* `ERR_PAGE_FAULT_LOOP` already works (fires after 5 retries). Not under test here.
* **Known harness defect:** `p` is a `run_from` argument that is never updated, so `ck.p == 0` for
  every fault and the triple cannot name a window. Fix that first — it is the reason attribution was
  impossible.

## Method

1. Copy the P03b harness. Give `VM_CKPT_FETCH`, `VM_CKPT_DISPATCH` and `VM_CKPT_NEXT` **distinct
   literal window numbers** so `p` is meaningful, and log **every** checkpoint (to a file), not just
   faults.
2. Run the fault-free baseline and dump the trace of the 8 dispatches around position 61.
3. Run with a single fault at position 61 and dump the same window from the retried run.
4. Diff the two traces: which dispatch executes twice, and what state differs as a consequence
   (`ip`, `w`, `sp`, `rsp`, the page image counter).
5. Decide between cause (a) and cause (b), with the trace lines that prove it. Then state the
   one-line fix: move the checkpoint after the fetch (a), or make the faulting primitive check
   residency before its first store (b).
6. If the trace shows something else, say what — with the lines.

## Record

| Item | Value |
| --- | --- |
| window numbers assigned | `p` values |
| re-executed dispatch | `(w, ip, p, token)` |
| state differing after retry | list |
| cause | (a) / (b) / other, with trace line numbers |
| one-line fix | text |

## Pass criteria

* the two traces are produced from the same build, differing only in the injection;
* the cause is named with specific trace lines, not inferred from the aggregate mismatch count.

## Failure criteria — and what each changes

* **Cause (a)** ⇒ the checkpoint moves after the token fetch; the resume state becomes "after the
  fetch, before execution". `01-proposal.md` §4.2 rule 2 gains that sentence, and word-boundary
  pinning stays the safer rule because it also covers (b).
* **Cause (b)** ⇒ primitives that can fault must check residency before their first store; that is a
  per-primitive audit, and word-boundary pinning removes the need entirely.
* **Both** ⇒ say so; word-boundary pinning is the only fix that covers both, and the per-primitive
  audit is not worth doing.
* **Neither, and the trace is inexplicable** ⇒ report the traces verbatim. That would mean the harness
  is lying, which is its own finding.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.2 rule 2 — one sentence: the checkpoint position, once proven.
* `probe/EVIDENCE.md` — an entry under E-014 with the trace excerpt, if it is conclusive.

## Do not

* Do not re-sweep positions; one position, two traces.
* Do not fix the interpreter as part of this probe — diagnose only.
* Do not touch the board, `docs/`, or `probe/uforth/`.
