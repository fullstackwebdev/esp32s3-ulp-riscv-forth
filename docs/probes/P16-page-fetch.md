# P16 — What does one page fetch actually cost, and what period absorbs it?

| | |
| --- | --- |
| Runs on | **board (exclusive)** — flashes the board; use `/dev/ttyACM1` |
| Time box | **15 min**, one run, hard cap |
| Depends on | P20 (page miss estimated at 0.99 ms), P19 (frames fixed at 4 × 512) |
| Blocks | the connected-mode period in §8; whether paging is usable in the loop at all |
| Serves | R5, R6, R3 |

## Question

The host model says a page miss costs **≈ 18 700 cycles ≈ 0.99 ms** — 26× a primitive dispatch — and
that this, not instruction choice, sets the wake period. Measure it:

1. Round trip with the main core **awake and polling**.
2. Round trip with the main core **awake but blocked** on a signal from the ULP.
3. Round trip with the main core in **deep sleep**, woken by the ULP, booting, servicing.
4. Bytes/second sustained, and the largest request that fits the mailbox.
5. The failure modes: server stopped, bad CRC, out-of-range address, and **two requests in flight**.

## Why it matters

A REPL line that touches cold code pays this cost per page. If it is ~1 ms, typing stays interactive
(resident code is 153 µs/frame). If it is 30 ms, paging must be a background activity and the
interpreter's hot set has to be pinned by policy. The design's answer is not "it's fine", it is a number
that decides the period.

## Given — do not re-derive

* P05: 122.6 cycles/tick, 6.46 µs/tick, 81-cycle wake entry, core 19 MHz.
* P06: the timer counts **sleep**; interval = sleep + work; period floor **22 ticks**; wake cause
  unreadable; **never write `COCPU_*` from the HP while the ULP may be mid-wake** (this wedged the board).
* P04: rings 128 B command / 256 B output; flow control by pacing.
* P20: dispatch 726 cycles; typing slice 23.7 ticks; page miss estimated 18 700 cycles.
* Mailbox layout: `docs/02-harness.md` §2 (request/response, `req_seq`/`rsp_seq`, 512 B page buffer).

## Method

1. Board lock, and **flash over `/dev/ttyACM1`** — the CH343's DTR/RTS drive EN/IO0, so UART0 is the
   recovery port. Recover with `esptool -p /dev/ttyACM1 chip-id` if it goes silent. Never use
   `/dev/ttyACM0` for flashing.
2. Task watchdog first; print a banner; stage the experiment behind a console command (`g`).
3. Build the minimum server: one FreeRTOS task, request slot in RTC memory, read/write 512 B to PSRAM,
   reply with `seq` + CRC. No Forth, no parsing — bytes only (R6).
4. ULP side: issue N read requests, record `rdcycle` deltas, publish min/median/p95/max as **ticks and
   µs** for each of the three configurations. 200 iterations each; report counts, not impressions.
5. Failure modes, each deliberate, each reported with the status the ULP saw: stop the server task; corrupt
   the CRC; ask for an address outside the window; issue a second request before the first is answered.
6. Report the break-even period: `ceil(page_miss_cycles / 122.6)` ticks, plus the margin the loop needs.

## Record

| Config | median ticks / µs | p95 | max |
| --- | --- | --- | --- |
| A awake, polling | | | |
| B awake, blocked on signal | | | |
| C deep sleep, woken, booted | | | |

Plus: bytes/s, largest request, four failure-mode outcomes, and the break-even period in ticks.

## Pass criteria

* all three configurations measured with a distribution;
* every failure mode produces a **named, detectable** outcome on the ULP — no hang, no silent zero-fill;
* the break-even period computed and compared with §8's 32–64 tick claim.

## Failure criteria — and what each changes

* **A > 2 ms** ⇒ paging per 512 B is too expensive for interactive use; pages become 1 KB and faults must
  batch, or only cold code pages at all. §8 changes.
* **C > 100 ms** ⇒ paging while the main cores sleep is unusable; autonomous mode loses paging and §8 must
  say so plainly.
* **No detectable no-server outcome** ⇒ the mailbox needs a watchdog counter the ULP can read; add it to
  `02-harness.md` §2.
* **Two in-flight requests corrupt state** ⇒ the protocol enforces a single outstanding request, and R6's
  acceptance item says so.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.2 rule 3 and §8 — measured latencies and the resulting period.
* `docs/02-harness.md` §2 — mailbox fields the measurement proved necessary; the single-outstanding rule.
* `docs/01-proposal.md` §10 R6 — restated with measured numbers.

## Do not

* Do not put any logic on the server beyond bytes, CRC, bounds check and partition calls. R6 is a hard
  requirement and this probe is where it erodes.
* Do not leave the ULP armed or the server task running; restore a known state and say what is flashed.
