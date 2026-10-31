# P35 — How big is the program when paging is dropped and the pool is re-spent?

| | |
| --- | --- |
| Runs on | **host only** (build + link) |
| Time box | **15 min**, one run, hard cap |
| Depends on | P32 (variant D, 1666 B spare without paging), P33/P34 (buffer + wrapper cost) |
| Blocks | the operator's actual question: "how much program do I get?" |
| Serves | R1, R5 |

## Question

The number in everyone's head is "908 B of Forth memory", which came from a budget that spent **2 466 B on
transparent paging**. If paging is dropped, that memory returns to the pool. What is `MEMSZ` then — i.e. how
much dictionary does the operator actually get, how many more words is that beyond the prelude, and where does
the ceiling come from?

## Why it matters

"Your program is 232 bytes" is the worst fact in this project, and it is an artefact of the paging budget, not
of the chip. The answer to the operator's question is a number, and it should be measured by maximising `MEMSZ`
until the link fails, in the variant that will ship.

## Given — do not re-derive

* P32: variant D engine 3916 B; dropping frames (2048) + table (250) + paged fetch channel (168) frees **2466 B**
  ⇒ **1666 B spare**, or **1346** with the C stack reserved inside the pool.
* P28: at 3 tasks the `MEMSZ` in the paged machine was 908 (1188 minus 280 for two extra task records).
* P26/P28: the prelude needs **676 B** resident at 16-bit tokens; dictionary spare was **232 B**.
* P02: 16-bit headerless words are **~28 B/word**; with headers ~39 B.
* P33/P34: a 512 B block buffer plus its transfer primitive is the paging cost in the new shape (one buffer, one
  primitive, Forth wrappers).

## Method

1. Start from P32's variant D, remove frames / `ptab` / `ptab_lru_reserve` / `pg_load` / `rd16_paged`, and add
   **one** 512 B buffer plus a transfer primitive worth ~100–200 B (use whichever P33/P34 measured; if neither
   report exists yet, reserve 200 B and say so).
2. **Maximise `MEMSZ`**: binary-search or step it upward until the link fails, and report the largest value that
   links. Do this twice — once with the C stack **not** reserved (optimistic), once with the 320 B stack carved
   inside the pool (honest).
3. Report the dictionary the operator actually gets:
   - `MEMSZ` in each case;
   - minus the 676 B prelude ⇒ **bytes available for the operator's own words**;
   - that figure divided by 28 and by 39 ⇒ words available headerless and with headers;
   - and the same arithmetic at `MEMSZ` 908 for comparison, so the gain is explicit.
4. Confirm allocation with `nm -S` (`mem` = the new `MEMSZ`, `frm`/`ptab` gone).
5. State in one sentence what does and does not scale: **what is now unbounded (data blocks, source in flash)**
   and **what is still bounded (`RESIDENT definitions`)** — because the interpreter fetches tokens from RTC RAM,
   so executable code must be resident.

## Record

| Case | `MEMSZ` | minus prelude | words @28 B | words @39 B |
| --- | --- | --- | --- | --- |
| paged machine (for reference) | 908 | 232 | ~8 | ~6 |
| non-paged, C stack not reserved | | | | |
| non-paged, C stack reserved | | | | |

## Pass criteria

* the maximum linking `MEMSZ` found by construction, not by arithmetic;
* the operator's-word budget stated as bytes **and** words, both headerless and with headers;
* the one-sentence statement of what scales and what does not.

## Failure criteria — and what each changes

* **`MEMSZ` grows by less than 500 B** ⇒ the freed 2 466 B went somewhere unexpected; report the `nm -S`
  inventory and name where. That is an accounting error and must be found before any size claim.
* **The gain is real but the words figure is still small (< 40 words)** ⇒ say so plainly, and note what the next
  lever would be (bigger block buffer for data, source-on-flash for code, or `FORGET` to recycle).
* **Link fails at 908 too** ⇒ something regressed; report the exact message.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.3/§4.4 — the re-spent budget and the operator's-word figures.
* `docs/07-status.md` — the corrected headline about program size.
* `docs/JOURNAL.md` — the number, and that "908 B" was a paging artefact.

## Do not

* Do not report `MEMSZ` without subtracting the prelude — the operator wants their own space, not the pool.
* Do not hand back a figure from arithmetic; the link is the answer.
* Do not touch the board, `docs/`, or other probes' directories.
