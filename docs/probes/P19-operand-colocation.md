# P19 — Can the compiler make N = 2 pages per dispatch?

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P03f (N = 3 measured) |
| Blocks | the frame line in §4.3 — the difference between 2048 B and 1536 B of frames |
| Serves | R5 |

## Question

Measured (P03f): a dispatch can touch **3 distinct pages** — token, inline operand, data — and frames
must be ≥ N+1, so 4 × 512 B = 2048 B. But the token and its inline operand are *adjacent in the
dictionary*; they only land in different pages when the pair straddles a boundary. If the compiler
**pads so a token and its operand never straddle**, does N drop to **2** — and does the sweep then pass
with **3 × 512 B = 1536 B** (or even 4 × 256 B)?

## Why it matters

512 B of frames is 512 B of dictionary, and §4.3 is currently **482 B short**. This is the cheapest of
the five levers: a padding rule in the compiler, paid for in dictionary bytes only at boundaries
(P02 says definitions average 39 B, so a straddle is rare).

## Given — do not re-derive

* P03f: N = 3; `frames ≥ N+1`; shrinking pages **raises** N, so 256 B pages are out unless N falls too.
* P03d: clean sweep at 4 × 512 (187 positions, 0 mismatches) with checkpoint-after-fetch.
* Harness: `probe/results/P03f-frames-4x256/` (which contains P03d's plus the layout constants).
* P02: inline literals are ~26.5 % of body bytes, so pairs are common.

## Method

1. Copy `probe/results/P03f-frames-4x256/` into `probe/results/P19-operand-colocation/`.
2. Add the compiler rule to the harness's dictionary writer: **before emitting any token, if fewer than
   8 bytes remain in the current page, pad to the next page boundary.** Then a token (2 or 4 B) plus an
   inline operand (2 or 4 B) always sits inside one page. Nothing else changes.
3. Measure, for the prelude and the RMW workload: **distinct pages touched per dispatch** (max and
   histogram), and the dictionary growth caused by padding (bytes and %).
4. Sweep three layouts with the rule in place: **3 × 512**, **2 × 512**, **4 × 256**. For each: does the
   prelude compile, does the RMW workload complete, and is the 187-position sweep clean?
5. If N is still 3 somewhere, name the dispatch and the three pages — that case is what breaks the rule.

## Record

| Layout | prelude compiles | RMW completes | sweep mismatches | max N | padding cost |
| --- | --- | --- | --- | --- | --- |
| 3 × 512 | | | | | |
| 2 × 512 | | | | | |
| 4 × 256 | | | | | |

## Pass criteria

* N measured with the rule in place, per layout;
* at least one layout **≤ 1536 B** that boots, completes the RMW workload, and sweeps clean;
* padding cost stated in bytes and as a percentage of dictionary.

## Failure criteria — and what each changes

* **N stays 3** ⇒ the third page is not the operand (name it). If it is the *data* page, no compiler
  rule can help, frames stay 2048 B, and §4.3 must find its 512 B elsewhere.
* **Padding costs > 5 % of the dictionary** ⇒ the rule is not free; state the real cost before adopting.
* **3 × 512 boots but 2 × 512 does not** ⇒ frames are 1536 B (saving 512), which is the number §4.3 needs.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.3 — the frame line, with the measured layout and padding cost.
* `docs/01-proposal.md` §4.2 rule 1/2 — the co-location rule as a compiler requirement if it works.
* `probe/EVIDENCE.md` — extend E-024.

## Do not

* Do not change the retry mechanism (P03d's) or the accessor implementation.
* Do not touch the board, `docs/`, or other probes' directories.
