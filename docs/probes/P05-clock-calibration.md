# P05 — Clock and cycle calibration

| | |
| --- | --- |
| Runs on | **board (exclusive)** — overwrites the firmware. Get approval first. |
| Time box | **15 min**, one run, hard cap |
| Depends on | — |
| Blocks | P06, P07, every budget figure in `01-proposal.md` §5 |
| Serves | open question Q1 |

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

How many CPU cycles are there per RTC_SLOW_CLK tick, how long is a wake, and what does one
`rdcycle`-to-`rdcycle` loop iteration cost? The vendor documentation does not state the ULP core
clock, so this must be measured.

## Why it matters

Every budget in §5 is `period_ticks × cycles_per_tick ÷ 2`. If `cycles_per_tick` is 100, a 1-tick
period gives 100 cycles per wake — far too few to run a token interpreter. If it is 4000, everything
is comfortable. Nothing else can be judged until this number exists.

## Method

1. Create a small IDF project under `probe/results/P05-clock/` with one ULP program and a main app.
2. The ULP program (one wake, then retire) does, in order, all inside one wake:
   - `t0 = rdcycle`;
   - a known-length dependent chain of `add` instructions (e.g. 1000× `addi`), `t1 = rdcycle`;
   - a known-length loop of loads from RTC RAM, `t2 = rdcycle`;
   - a known-length loop of 8 byte-accesses emulating the prototype's `rd32`, `t3 = rdcycle`;
   - write `t0..t3` and a wake counter into shared variables.
3. The main app sets the ULP period to several values (1, 10, 100, 10 000 ticks), runs it, and reads
   the results. It also measures wall-clock time of `N` wakes with `esp_timer` so the tick count can
   be cross-checked against the 136 kHz RTC_SLOW_CLK.
4. From the deltas and the instruction counts, compute cycles per instruction (should be ≥ 1 and
   constant), cycles per RTC tick, and the implied core frequency. **State the implied frequency and
   the uncertainty**; do not present a single number without its error bar.
5. Measure wake overhead: `rdcycle` at the top of `main` and the wake counter, over 1000 wakes, to get
   residual work per wake.
6. Repeat with `CONFIG_ULP_COPROC_RESERVE_MEM` at 8176 to confirm the numbers do not depend on the
   reservation size.

## Record

| Item | Value |
| --- | --- |
| cycles per `addi` (dependent chain) | |
| cycles per RTC RAM load | |
| cycles per byte-access emulation of `rd32` | |
| cycles per RTC tick | |
| implied core frequency (with uncertainty) | |
| wake overhead, cycles | |
| wall-clock vs tick cross-check | |
| period values tested | |

## Pass criteria

* `cycles_per_tick` reproducible across three runs within 5 %;
* implied frequency consistent with the instruction counts (no anomaly > 2×);
* the RTC_SLOW_CLK cross-check agrees with 136 kHz within the timer's own quantisation.

## Failure criteria — and what each changes

* **`cycles_per_tick` < 200** ⇒ a 1-tick period cannot run a token interpreter; §8's "connected mode
  1–4 ticks" is impossible and must become "N ticks", with the echo latency restated.
* **Cycles per byte-access ≥ 4** ⇒ the prototype's byte-wise `rd32` costs 32+ cycles per cell access;
  D7 in `03-prototype-review.md` becomes a *required* fix, not an optimisation, and it moves into the
  critical path.
* **`rdcycle` does not count what we assume** (e.g. wraps at 16 bits) ⇒ report it; every budget
  formula needs a different basis.

## Doc deltas to hand back

* `docs/01-proposal.md` §5 — replace "cycles_per_tick is measured on the chip by calibration" with
  the measured value and the resulting budget for the chosen period.
* `docs/01-proposal.md` §8 — restate connected-mode periods in ticks if 1–4 is impossible.
* `docs/03-prototype-review.md` D7 — mark it required or optional per the measurement.
* `probe/EVIDENCE.md` — new entry with the numbers and the project path.

## Do not

* Do not publish a core frequency from a datasheet or from the S2/S3 HP core numbers. Only measured.
* Do not leave the board running a test image; restore a known state and say what is flashed.
* Do not touch host-only probes or `docs/`.
