# P32 — Audit the 322 bytes, then price what the machine keeps

| | |
| --- | --- |
| Runs on | **host only** (link + `nm`) |
| Time box | **15 min**, one run, hard cap |
| Depends on | P31 (3412 engine, 296 B over, 322 B unexplained) |
| Blocks | the port, and the decision about what the machine gives up |
| Serves | R1–R5 |

## Question

Two things, in this order.

1. **The accounting is wrong by 322 B.** §4.3's fixed lines sum to 4418, the link says 4740. Until that is
   explained, "296 B short" is a number inside a bigger unknown, and nobody should drop a requirement to fix
   an unexplained gap.
2. **What does the machine cost if it keeps a usable language?** P31's derived 40-primitive set is circular —
   it removes `I`, `J`, `UNLOOP` (no user `DO … LOOP`), `GPIO!` (no output pin), `'`, `(`, `."` and
   `CONSTANT`. Price them back and see where that lands.

## Why it matters

The difference between "296 B short" and "the machine cannot exist" is exactly this audit. And the difference
between "a Forth that runs the demo" and "a Forth someone can program" is those eight primitives.

## Given — do not re-derive

* P31: engine 3412 (40 prims + libgcc fixes), region need 8152, pool 7856 ⇒ **296 B over**; fixed lines
  measured **4740** vs §4.3's 4418 ⇒ **322 B unexplained**; true engine ceiling **3116**.
* §4.3 lines as tabled: frames 2048, VM+table 400, rings 600, C stack 320, hooks 142, `mem` 908.
* P29's `nm -S` inventory (real, from the link): `frm` 2048, `ptab` 16, `ptab_lru_reserve` 234, `cmd_ring` 128,
  `out_ring` 256, `mailbox` 216, `tib` 128, `mem` 908, `vm_live` 136, `tsk` 420.
* P21: C stack worst case 244 B, recommended 320 (76 margin).
* P27: 140 B per task; P13: single-task stack peak 20 + 7 cells.

## Method

**Part 1 — the audit.** Add up the `nm -S` inventory above and compare with §4.3. The likely culprits, in order:
`tsk` 420 (three task records) counted inside "rings" or not at all; `tib` 128 and `mailbox` 216 not in any line;
`ptab_lru_reserve` 234 vs the tabled 250; `.rodata` counted twice or not at all. Produce a line-by-line table:
*§4.3 line → `nm` symbol(s) → size → discrepancy*. The 322 B must be **named**, not waved at.

**Part 2 — price the language back.** Build, from P31's variant C, one additional variant **D** that restores
the primitives a programmer needs:

| Primitive | Why it must come back |
| --- | --- |
| `I`, `J`, `UNLOOP` | without them a user cannot write `DO … LOOP`, though the prelude defines it |
| `GPIO!` | without it nothing can drive an output pin |
| `'` | `' NAME` at the REPL, and reading a tick from the input stream |
| `CONSTANT` | defining a named value, which every Forth tutorial starts with |
| `(`, `."` | comments in source; printing a string |

Report D's engine size, and the resulting gap against the **corrected** ceiling from Part 1.

**Part 3 — price the three options, do not choose one.** For each, give bytes and what it costs functionally:
(a) drop paging from the first machine (frames 2048 + `resolve`/`pg_load`/paged read path out, pool in);
(b) two tasks instead of three (−140 B, and one fewer concurrent thing);
(c) shrink `mem` toward the measured resident need (676 B) and say what the dictionary loses.

## Record

| Part | Result |
| --- | --- |
| audit: 322 B named | line-by-line table |
| corrected engine ceiling | bytes |
| D: engine with the language restored | bytes, gap vs corrected ceiling |
| (a) drop paging | bytes freed, cost |
| (b) two tasks | bytes freed, cost |
| (c) `mem` → 676 | bytes freed, what is lost |

## Pass criteria

* **every byte of the 322 B discrepancy attributed to a named symbol or line** (or the table's arithmetic
  shown to be the error);
* variant D built and linked, with its real result;
* the three options priced and **not chosen**.

## Failure criteria — and what each changes

* **The 322 B turns out to be §4.3's arithmetic** ⇒ fix the table; the machine's gap is 296 B on a corrected
  ceiling, and part 3 decides.
* **D fits after the audit** ⇒ the machine exists with a usable language; report the numbers and stop the
  budget phase.
* **D does not fit and no option is cheap** ⇒ say so plainly: the options are the operator's scope decision,
  and the session's recommendation is (a) — a non-paged first machine — because paging is the only requirement
  that can be added later without changing the language.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.3 — the corrected table with every `nm` symbol mapped to a line.
* `probe/EVIDENCE.md` — the audit table and D's numbers.
* `docs/JOURNAL.md` — the decision or the options, whichever applies.

## Do not

* Do not drop a requirement to make the link pass. Price it, report it, and let the operator choose.
* Do not trust the tabled numbers over `nm -S` — the symbols are the ground truth.
* Do not touch the board, `docs/`, or other probes' directories.
