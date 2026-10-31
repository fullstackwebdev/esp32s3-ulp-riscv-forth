# P03e — Does a store-then-fault primitive repeat its store on retry?

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P03d (verified harness) |
| Blocks | the last open risk in §4.2 rule 2 |
| Serves | R5 |

## Question

P03d cleared primitive-granular retry for a workload of single-access primitives: 0 mismatches over 187
positions. But a primitive that **stores and then faults on a second access inside the same dispatch**
would repeat its store when the dispatch is re-entered. No workload so far contains such a word. Does
it actually break?

One workload, one added primitive, one sweep.

## Given — do not re-derive

* Harness: `probe/results/P03d-checkpoint-fix/` — verified, 0 mismatches, checkpoint after the fetch.
  Copy it; do not change the retry mechanism.
* Baseline digest `chk=4f99db40 sp=1 rsp=0`, 187 dispatch positions, 83 faultable.
* `ERR_PAGE_FAULT_LOOP` and `ERR_RETRY_CAP` both work; they are not under test.

## Method

1. Copy P03d's harness into `probe/results/P03e-store-then-fault/`.
2. Add **one** step to the workload that performs a genuine read-modify-write across the page boundary
   inside a single dispatch — for example an increment-in-place (`+!`) on a cell in a page that is not
   resident, or a two-cell update (`2!`) whose two cells live in different pages. It must touch memory
   twice within one dispatch, and both touches must be able to fault.
3. Re-establish the baseline (faults disabled) and record the new digest. It will differ from
   `4f99db40` because the workload changed — that is expected; what must hold is that it is
   reproducible across two runs.
4. Sweep: one fault at every dispatch position, compare the final page image and stacks against the new
   baseline. Report mismatches with `(w, ip, p, addr)`.
5. For the first mismatch (if any), dump the six checkpoints around it in both runs — the P03c
   technique — and state whether the cause is "store executed before the fault, repeated on retry".

## Record

| Item | Value |
| --- | --- |
| new baseline digest, two runs | must match each other |
| positions tested / `no_access` | n / n |
| **mismatches** | target 0 |
| first mismatch | `(w, ip, p, addr)` + trace if non-zero |
| cause | store-repeated / other |

## Pass criteria

* 0 mismatches with the read-modify-write primitive in the workload, or a mismatch that is clearly
  attributable to store repetition and **documented with a trace** (that is a finding either way, but it
  must be proven, not inferred).

## Failure criteria — and what each changes

* **0 mismatches** ⇒ fine-grained retry is cleared for store-then-fault primitives too; §4.2 rule 2's
  "unobserved risk" paragraph is deleted and the acceptance box is ticked on the host side.
* **Mismatches from a repeated store** ⇒ §4.2 rule 2 gains a per-primitive rule: **every primitive that
  can fault checks residency before its first store**, and the primitive set is audited for
  multi-access words (`+!`, `2!`, `MOVE`, `FILL`, string ops). This is a small, bounded audit — say how
  many primitives in the current set are affected.
* **Baseline is not reproducible** ⇒ `BLOCKED: baseline unstable`, because the new workload is
  nondeterministic and no sweep result would mean anything.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.2 rule 2 — delete the "unobserved risk" paragraph, or replace it with the
  per-primitive residency rule.
* `docs/01-proposal.md` §10 R5 — the store-then-fault item, restated.
* If the audit is needed: list the affected primitives with their access counts.

## Do not

* Do not change the retry mechanism; P03d's version is the one under test.
* Do not sweep other workloads, other frame counts, or timing.
* Do not touch the board, `docs/`, `probe/uforth/`, or other probes' directories.
