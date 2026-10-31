# P07 — Byte server: fault cost awake vs asleep, throughput, failure modes

| | |
| --- | --- |
| Runs on | **board (exclusive)** — overwrites the firmware. Get approval first. |
| Time box | **15 min**, one run, hard cap |
| Depends on | P05 (cycles/tick), P06 (retire semantics) |
| Blocks | `01-proposal.md` §4.2 rule 3, R6 acceptance, the whole paging story |
| Serves | R6 (all items), R5 (fault cost), open question Q4 |

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

What does one storage round trip cost the ULP — in RTC ticks — with the main cores already awake, and
with them woken from deep sleep by the ULP? What throughput does the mailbox give, and what happens
when the server is absent, slow, or returns bad data?

## Why it matters

§4.2 rule 3 asserts 50–200 µs awake and "milliseconds" asleep. Those are guesses, and they decide
whether paging is usable at all: a 512 B page fetched in 5 ms means a cold definition costs two
thirds of a 7.35 µs-tick... in other words, hundreds of ticks. If the awake number is 10× worse than
guessed, the page size and the hot-set rule both change.

## Method

1. Project under `probe/results/P07-byte-server/`.
2. Implement the **minimum** real server: a dedicated FreeRTOS task on the main core, a request slot in
   RTC memory (the layout in `docs/02-harness.md` §2), service for "read 512 B from PSRAM" and
   "write 512 B to PSRAM", reply with a sequence number and a CRC-16. No Forth, no parsing, no
   decisions — a byte mover, as R6 requires.
3. ULP side: a program that issues `N` read requests of 512 B and writes `rdcycle` deltas.
4. Measure four configurations, 200 iterations each, report min/median/p95/max in **ticks and µs**:
   - **A.** main cores awake and polling the request slot;
   - **B.** main cores awake, blocked on an event the ULP signals via `ulp_riscv_wakeup_main_processor()`;
   - **C.** main cores in deep sleep, ULP wakes them with `ulp_riscv_wakeup_main_processor()`, they
     boot, find the request, service it;
   - **D.** as C but with the ULP requesting a *second* page immediately (steady-state back-to-back).
5. **Throughput:** bytes/second sustained in configuration A, and the largest request size that fits
   the mailbox before you need chunking.
6. **Failure modes**, each deliberately induced:
   - stop the server task ⇒ the ULP must see no reply; record how many ticks before it gives up and
     what it can detect (`ERR_NO_SERVER` is the intended status);
   - corrupt the CRC ⇒ the ULP must reject the page;
   - ask for an address outside the PSRAM/flash window ⇒ the server must refuse with a status, not
     clamp;
   - two requests in flight (ULP writes a new `req_seq` before the reply) ⇒ record what happens; this
     decides whether the protocol needs an ARQ or a single outstanding request rule.
7. Report the PSRAM read/write cost separately from the round trip where possible (e.g. 4 B vs 512 B
   requests), so the fixed and marginal costs are distinguishable.

## Record

| Item | A | B | C | D |
| --- | --- | --- | --- | --- |
| round trip, median ticks / µs | | | | |
| p95 / max ticks | | | | |
| sustained bytes/s | | | | |

Plus: largest single request, failure-mode observations (4 cases with exact statuses), and whether one
outstanding request is sufficient.

## Pass criteria

* all four configurations measured with a distribution, not a single sample;
* all four failure modes produce a **detectable** outcome on the ULP (a status it can act on), not a
  hang;
* the "no server" case is bounded: a maximum retry count or timeout in ticks, reported.

## Failure criteria — and what each changes

* **Configuration A median > 1 ms** ⇒ paging per 512 B page is too expensive for anything but cold
  code. `01-proposal.md` §4.2 rule 3 changes: pages become 1 KB and faults must be batched, or the
  design moves to "resident prelude + paged user code" explicitly.
* **Configuration C > 100 ms** ⇒ paging while the main cores sleep is unusable; the design must
  require the main cores awake for any paged access, and the autonomous mode in §8 loses paging
  (state that plainly).
* **No detectable no-server outcome** ⇒ the mailbox needs a watchdog counter the ULP can read before
  it retires; add it to the layout in `02-harness.md`.
* **Two in-flight requests corrupt state** ⇒ the protocol must enforce a single outstanding request,
  and the acceptance item in R6 must say so.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.2 rule 3 — replace the guessed latencies with the measured table.
* `docs/08`? no — `docs/01-proposal.md` §8 — if paging requires awake main cores, say it there.
* `docs/02-harness.md` §2 — the mailbox layout gains/keeps exactly the fields the measurement proved
  necessary; the protocol gains the single-outstanding rule.
* `docs/01-proposal.md` §10 R6 — restate the fault-count item with measured numbers.

## Do not

* Do not put any logic on the server beyond bytes, CRC, bounds check and partition calls. R6 is a
  hard requirement and this probe is where it would silently erode.
* Do not measure with the server polling in a tight loop and call it "awake" for configuration B —
  the point is to compare polling vs interrupt-driven vs boot.
* Do not leave the board asleep with the ULP armed; restore and say what is flashed.
