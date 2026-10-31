# P18 — Do pin edges survive sleep, and how many coalesce?

| | |
| --- | --- |
| Runs on | **board (exclusive)** — flashes; use `/dev/ttyACM1` |
| Time box | **15 min**, one run, hard cap |
| Depends on | P06 (wake cause unreadable), P23 (doorbell) |
| Blocks | R3's GPIO event items — the event loop's whole input story |
| Serves | R3 |

## Question

P06 established that the wake-cause register reads 0 on every wake, so cause must come from **polling RTC-IO
interrupt status at the start of each wake**. Nobody has tested that fallback. Three things are unknown:

1. Does an edge that occurs **while the ULP sleeps** leave a latch that is still set when it wakes?
2. If **N edges** occur during one sleep, how many are visible — one, or N?
3. What is the maximum edge rate that is not lost, and the edge→event latency?

## Why it matters

Everything about pin events depends on this: `ON-GPIO`, the event ring's coalescing rule, and R3's "exactly
one event per pin per wake, never lost, never duplicated". If latches do not survive sleep, pins must be
polled by the HP core instead — which changes who owns the GPIO requirement.

## Given — do not re-derive

* P06: `RTC_CNTL_SLP_WAKEUP_CAUSE` = 0 on every wake; both wake sources can be armed
  (`RTC_CNTL_ULP_CP_TIMER_REG = 0xA0000000`); the timer counts sleep; period floor 22 ticks (142 µs).
* P23: `ulp_riscv_wakeup_main_processor()` works, 176 µs with the HP blocked.
* Pin discipline: **use GPIO4**; never GPIO19/20 (native USB), 0/3/45/46 (strapping), 43/44 (UART0), 26–37
  (flash/PSRAM).

## Method

1. Board lock; watchdog first; banner; stage behind a console `g`.
2. Arm the ULP on the **timer only** (no GPIO wakeup), period 1 000 ticks. On each wake the ULP reads the
   RTC-IO interrupt status for GPIO4, writes it plus a counter to shared memory, and clears it.
3. From the HP, drive GPIO4 with a known number of edges **while the ULP is asleep**, for N = 2, 5, 50, 500,
   5 000. For each N report: status bits seen, events the ULP counted, and whether the count is 1, N, or
   something else.
4. Sweep edge rate: 1 Hz, 100 Hz, 10 kHz, 100 kHz. For each, send 1 000 edges over one sleep and report how
   many the ULP observes. Find the rate at which edges start being lost.
5. Measure **edge → wake latency**: timestamp on the HP when the edge is driven, `rdcycle` in the ULP at
   wake start; report min/median/max in ticks and µs.
6. Confirm the latch clears: after the ULP clears the status, a second wake with no new edge must report
   zero.

## Record

| N edges during sleep | status bits | events counted | interpretation |
| --- | --- | --- | --- |
| 2 | | | |
| 5 | | | |
| 50 | | | |
| 500 | | | |
| 5 000 | | | |

Plus the rate sweep table (edges sent / observed / lost per rate), and the latency distribution.

## Pass criteria

* latches proven to survive sleep (or proven not to, with the register evidence);
* the coalescing rule stated as a number: *k* edges → *m* events;
* a maximum non-losing edge rate reported;
* latency measured with a distribution;
* the latch provably cleared between wakes.

## Failure criteria — and what each changes

* **Latches do not survive sleep** ⇒ pin events must be owned by the HP core, not the ULP. R3's GPIO items
  move to the bridge, and the ULP's event ring becomes timer-only.
* **Only one edge is ever visible per sleep** ⇒ the ring's contract is "level, not edge": a pin held high for
  two edges is indistinguishable. §5's event semantics must say so.
* **Edges are lost above some rate** ⇒ that rate is a published limit, and the design must either accept it
  or add a counter in hardware/HP.
* **Latency > one period** ⇒ an event can be attributed to the wrong wake; the event timestamp becomes
  "somewhere in the previous period", and R3's item must be restated.

## Doc deltas to hand back

* `docs/01-proposal.md` §5 — the event semantics, with the coalescing rule and the losing rate.
* `docs/01-proposal.md` §10 R3 — the GPIO item, restated with measured limits.

## Do not

* Do not leave the ULP armed or a pin driven; restore and say what is flashed.
* Do not use GPIO19/20 for anything, ever, on this board.
