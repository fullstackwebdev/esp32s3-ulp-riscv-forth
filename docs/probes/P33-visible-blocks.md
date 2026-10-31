# P33 — Does a visible block layer fit where transparent paging did not?

| | |
| --- | --- |
| Runs on | **host only** (build + link + host execution) |
| Time box | **15 min**, one run, hard cap |
| Depends on | P32 (variant D: 3916 engine, 800 B over), P16 (144 µs per fetch) |
| Blocks | R5 for v1 — the operator's preferred shape |
| Serves | R5, R1, R3 |

## Question

Transparent paging costs **2 466 B** (frames 2 048 + table 250 + paged fetch path 168) plus a fault/retry state
machine, and it does not fit alongside a programmable language. But most of that buys **transparency** — the
ability to touch an arbitrary address from `@`/`!` without knowing it is not resident.

A **visible block interface** needs none of it: one buffer, one synchronous word, no table, no frames in the
address space, no fault path. **Does that fit — with the language, three tasks, and the console?

## Why it matters

If it fits, R5 survives in the only form this chip can afford: block storage you ask for by name, exactly the
1980s Forth block file. If it does not, paging is genuinely absent from v1.

## Given — do not re-derive

* P32 variant D: engine **3916 B**, region need 8656 of 7856 = **800 B over**; by option (a) dropping
  transparent paging frees **2 466 B** ⇒ **1 666 B spare** (1 346 with the C stack reserved inside the pool).
* P16: a 512 B fetch costs **144 µs** (2 740 cycles) with the main core polling; **3.55 MB/s** sustained;
  two requests in flight corrupt silently with a valid CRC ⇒ **exactly one outstanding request**.
* P23: doorbell wake costs **176 µs** with the main core blocked.
* P18: a pin edge latches through sleep and coalesces to one event per wake.
* Mailbox + rings are already budgeted at **600 B** (`mailbox` 216 + `out_ring` 256 + `cmd_ring` 128).
* P26: the minimal layer is 1024 B headerless; P28: `mem` 908, resident need 676.

## Method

1. Copy P32's variant D into `probe/results/P33-visible-blocks/`. **Do not remove the language** — D is the
   baseline because `I J UNLOOP GPIO! ' CONSTANT ( ."` are what makes it a Forth someone can program.
2. Remove exactly what transparency needed and nothing else: frames (`frm` 2048), page table (`ptab` 16 +
   `ptab_lru_reserve` 234), and the paged read path (`pg_load` 108, `rd16_paged` 60). Record the engine delta.
3. Add the visible layer, **in Forth where possible**:
   - one **512 B buffer** (its placement and cost stated);
   - `BLOCK ( n -- addr )` — one request, bounded wait, copy, return the address;
   - `UPDATE` (mark dirty) and `SAVE` (send it back);
   - a **single-outstanding** guard, and a **named** failure for "no answer" (`ERR_NO_SERVER`) and for a bad
     checksum (`ERR_CRC`). No silent zero-fill, no unbounded spin.
   Keep the C-side addition to what genuinely cannot be Forth: the request/response words over the mailbox.
4. Compile the layer + prelude, then measure: engine size, the buffer's cost, and the **spare** against the pool
   (with and without the C stack reserved).
5. **Run it on the host** against a fake mailbox: `0 BLOCK` returns a buffer address and the bytes match the
   fake server's block 0; `UPDATE`/`SAVE` writes back; the no-answer case raises `ERR_NO_SERVER`; two requests in
   flight are refused (`ERR_BUSY`). A layer that does not execute is not an answer.
6. Report what R5 becomes in this shape, in one sentence, for the operator to accept or reject.

## Record

| Item | Value |
| --- | --- |
| engine after removing frames/table/fetch path | |
| engine after adding the visible layer | |
| buffer cost | |
| region need vs 7856 | |
| **spare** (and with the C stack reserved) | |
| host execution: BLOCK / UPDATE+SAVE / ERR_NO_SERVER / ERR_BUSY | pass or fail each |

## Pass criteria

* the machine **links** with the language, three tasks, the console and the visible block layer;
* the layer **executes** on the host: read, write back, and both named failures;
* the spare stated as a number, both ways.

## Failure criteria — and what each changes

* **Does not link** ⇒ report the overrun and the symbol. Then the buffer is the candidate: try 256 B and say
  what block size that implies.
* **The layer needs more than ~200 B of C** ⇒ report the actual figure and what it is doing; a visible block
  interface that costs a quarter of transparent paging needs justifying.
* **`BLOCK` cannot be bounded** ⇒ if the wait cannot be capped, it must be two-phase (request, then
  `BLOCK?`), and that changes the Forth API — report before building it.
* **Fits with < 200 B spare** ⇒ say so; a machine that fits with 150 B has no room for the operator's words and
  is not really a Forth.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.4 — the visible-block variant, its cost and its spare; and §7 for the R5 wording.
* `docs/06-repl.md` if the console gains a block-list command.
* `docs/JOURNAL.md` — the decision and what R5 became.

## Do not

* Do not keep any part of the transparent machinery "just in case" — the point is to measure what transparency
  costs.
* Do not let `BLOCK` spin unbounded or return a zero-filled buffer.
* Do not touch the board, `docs/`, or other probes' directories.
