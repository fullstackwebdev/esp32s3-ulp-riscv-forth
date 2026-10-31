# P06 — Wake semantics: period overrun, and timer + GPIO together

| | |
| --- | --- |
| Runs on | **board (exclusive)** — overwrites the firmware. Get approval first. |
| Time box | **15 min**, one run, hard cap |
| Depends on | P05 (cycles per tick) |
| Blocks | the deadline model in `01-proposal.md` §5, R3 acceptance |
| Serves | open question Q2, R3 items about retiring and GPIO events |

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

1. If a wake runs longer than the period, what happens — is the next tick lost, latched and fired
   immediately, or does the core re-enter mid-flight?
2. Can the timer wakeup and an RTC-IO (GPIO) wakeup be armed at the same time, and if so, is the wake
   cause attributable?
3. What is the latency from a GPIO edge to the ULP seeing the event?

## Why it matters

§5 claims "each wake retires so the timer re-arms" and Rule 3 of §4.2 claims faults cost ticks. If an
overrunning wake *latches* a pending tick, the loop self-corrects; if it *loses* one, timing drifts
and every period-based budget is wrong. And §5 requires GPIO events to be timestamped, which is
meaningless if the two wake sources cannot coexist.

## Hard-won constraints from the first attempt (read before flashing)

The first P06 run flashed cleanly and then wedged the board: `/dev/ttyACM0` kept enumerating but every
write timed out, for hours, through every software reset path. **A human had to press EN.** The board is
now healthy again and running P05's known-good image. Therefore, in this attempt:

* **Flash over `/dev/ttyACM1` (UART0), not `/dev/ttyACM0`.** The CH343's DTR/RTS drive EN/IO0, so UART0
  can always force download mode. Recover with `esptool -p /dev/ttyACM1 chip-id`; that resets the chip.
* **Never touch GPIO19 or GPIO20** — they are the native USB D-/D+. Driving them kills the USB-JTAG
  peripheral and is the leading suspect for the wedge. Also avoid GPIO0, 3, 45, 46 (strapping), GPIO43,
  44 (UART0), and GPIO26–37 (flash/PSRAM). **Use GPIO4** for the wake pin.
* **Enable the task watchdog first**, before UART init and before any ULP call, so a hang in our own code
  resets the chip instead of eating the console.
* **Print a banner immediately** and stage the experiment behind a console command (`g` = go). If the
  board goes silent, the last printed stage says where.
* **Keep the image you flash plus its `flash_args`** in your result directory.

## Given (measured by P05 — do not re-derive)

* **122.6 cycles per RTC tick**, **81 cycles of wake entry**, core **19.0 MHz ± 1.5 %**, RTC_SLOW_CLK
  **154.9 kHz** (1 tick = **6.46 µs**). A 1-tick wake therefore has only **41 usable cycles**, so a
  period of 1 tick is already an overrun for any real work — which is exactly what test 2 needs.
* `rdcycle` is a 32-bit counter **reset at each wake** (it starts at 81 in `main`). Consecutive-wake
  deltas must be derived from the wake counter plus `esp_timer` on the HP side, not from `rdcycle`
  across wakes.
* Convert ticks to µs with **154.9 kHz**, never 136 kHz.

## Method

1. Project under `probe/results/P06-wake/`.
2. **Overrun test.** ULP program reads a `delay_cycles` value from shared memory and busy-waits that
   long (`rdcycle`-bounded), incrementing `wake_count` and writing `rdcycle` at wake start. Main app
   sets period = 1 tick and sweeps `delay_cycles` from 0.1× to 10× the measured budget. Record:
   `wake_count` delta over a fixed wall-clock window, and the distribution of `rdcycle` deltas between
   consecutive wake starts. Interpret:
   - `wakes/sec ≈ 1/period` and constant ⇒ tick lost during overrun;
   - `wakes/sec < 1/period` and bursts ⇒ tick latched;
   - never returning / counter stuck ⇒ re-entry or hang.
3. **Wake source coexistence.** Arm the timer (period = 100 ticks) *and* the RTC-IO wakeup on one pin
   (`ulp_riscv_config_wakeup_source` only picks one — this test is about whether setting the register
   bits directly for both works). Toggle the pin at a rate much slower than the timer period and
   record, per wake, which cause was recorded. Both causes must appear and be correctly attributed.
4. **GPIO latency.** Toggle the pin from the main app with `esp_timer` timestamps; the ULP records
   `rdcycle` and a wake counter on the GPIO wake. Report latency distribution (min/median/max) in
   ticks and µs.
5. **Retire check.** Confirm `DONE` is set on every path (normal return, `ulp_riscv_halt`, and the
   error path) by verifying the timer keeps firing after each: `wake_count` must keep increasing
   after an intentionally aborted wake.

## Record

| Item | Value |
| --- | --- |
| overrun verdict | lost / latched / re-entry / hang |
| wakes/sec at 0.1×, 1×, 2×, 10× budget | |
| `rdcycle` delta distribution between wakes | min/median/max |
| both wake sources armed? | yes/no, with the register writes used |
| cause attribution correctness | n correct / n |
| GPIO edge → event latency | ticks, µs |
| retire after abort | confirmed yes/no |

## Pass criteria

* overrun behaviour identified and reproducible;
* if both sources can be armed: both causes observed and attributed correctly;
* GPIO latency measured with a distribution, not a single sample;
* `wake_count` never stops advancing in the normal and aborted cases.

## Failure criteria — and what each changes

* **Tick lost on overrun** ⇒ §5's budget must include a hard stop *before* the period expires, and
  the safety divisor changes from `÷2` to whatever measurement supports. State the new divisor.
* **Both sources cannot coexist** ⇒ §5's GPIO handling becomes "poll RTC-IO status at the start of
  every timer wake", and R3's "timestamped edge" item is restated as "coalesced within one period".
* **Re-entry (no reset)** ⇒ the whole "wake = reset" model in `00-background.md` §2.4 is wrong for
  overruns, and §5 must handle a non-reset continuation. This would be a significant finding; report
  it with raw traces.

## Doc deltas to hand back

* `docs/01-proposal.md` §5 — the budget divisor, the overrun rule, and the GPIO paragraph.
* `docs/01-proposal.md` §10 — R3 items about retiring and GPIO events.
* `docs/00-background.md` §2.4 — correct the execution-model table if overrun re-enters instead of
  resetting.

## Do not

* Do not test overrun with `esp_rom_delay_us` or anything that yields; the ULP must genuinely
  overrun.
* Do not infer the wake cause from the wake count; read the actual status registers.
* Do not leave the board in a state where the ULP is spinning; restore and say so.
