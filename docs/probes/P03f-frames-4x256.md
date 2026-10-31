# P03f — Does 4 × 256 B kill the three-page livelock?

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P03e (the livelock), P03d (verified retry) |
| Blocks | §4.3's frame layout; P16's expectations |
| Serves | R5 |

## Question

P03e showed a single dispatch touching **three pages at once** (token, inline operand, data) livelocks
with **2 × 512 B** frames — zero forward progress, 302 retries, `ERR_RETRY_CAP` — even with faults
disabled. The proposed fix is **4 × 256 B** (same 1024 B, four slots). Does the sweep become clean?

## Why it matters

This is the last structural unknown in the paging design. If four smaller frames fix it, frames stay at
1024 B and nothing else moves. If it does not, the machine needs more frame RAM than the budget has, and
that is a §12-level problem.

## Given — do not re-derive

* P03e: the livelock, the three-address cycle (`602`, `537397248`, `1500`), `ERR_RETRY_CAP` after 302
  page loads, `ERR_PAGE_FAULT_LOOP` unable to fire because the key alternates `p=1 ↔ p=2`.
* P03d: checkpoint **after** the token fetch; 0 mismatches over 187 positions at 2 × 512 B.
* Harness: `probe/results/P03e-store-then-fault/` (which is `P03d`'s plus the RMW step) and
  `probe/results/P03d-checkpoint-fix/` (clean, no RMW).
* Server latency in the sim: `SERVER_LATENCY=8` per page load.

## Method

1. Copy `probe/results/P03d-checkpoint-fix/` (the clean one) into `probe/results/P03f-frames-4x256/`.
2. Change exactly two constants: **page size 512 → 256**, **frames 2 → 4**. Nothing else. Total frame
   RAM stays 1024 B.
3. Run: (a) the fault-free baseline — must complete with no `ERR_RETRY_CAP`; (b) the full sweep, one
   fault at every dispatch position; (c) the P03e RMW workload, which is the case that livelocked.
4. Report faults per workload under both layouts (2 × 512 vs 4 × 256) so the cost of smaller pages is a
   number: more faults, each moving half the data.
5. If it still livelocks, list the address cycle and the number of distinct pages it needs — that
   number is what the design must accommodate.

## Record

| Item | 2 × 512 (P03d/P03e) | 4 × 256 (this) |
| --- | --- | --- |
| RMW workload completes | **no** (`ERR_RETRY_CAP`) | ? |
| fault-free baseline | livelocked | ? |
| mismatches over the sweep | 0 (187 positions) | ? |
| faults per workload | | |
| distinct pages in the worst cycle | 3 | ? |

## Pass criteria

* the RMW workload completes without `ERR_RETRY_CAP`;
* the sweep is clean (0 mismatches) at 4 × 256, or a mismatch is documented with a trace;
* faults-per-workload reported for both layouts, so the trade is quantified.

## Failure criteria — and what each changes

* **Still livelocks at 4 × 256** ⇒ the requirement is *N+1 frames where N is the pages a dispatch
  touches*, and N is larger than 3 at 256 B. Then frames must grow beyond 1024 B, which comes out of the
  dictionary — §4.3 changes and resolution A may no longer close.
* **Clean but faults double** ⇒ acceptable; record the number so P16 can price it.
* **Baseline now mismatches** ⇒ the two constants changed semantics somewhere; report `FAIL` with the
  digest, do not sweep.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.3 — confirm or correct the frame layout.
* `docs/01-proposal.md` §4.2 rule 2 — the frame-capacity sentence, with the measured N.
* `probe/EVIDENCE.md` — extend E-020.

## Do not

* Do not change anything except page size and frame count.
* Do not touch the board, `docs/`, or other probes' directories.
