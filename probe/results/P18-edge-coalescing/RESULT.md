# P18 — Do pin edges survive sleep, and how many coalesce?

**Verdict: PASS.** The RTC-IO latch survives the ULP's sleep, `k` edges inside one wake interval
become exactly **1** event for 2 ≤ k ≤ 5 000, the latch reads 0 on the following wake after the ULP
clears it, latency is ≤ 1 period, and the losing rate is **1 edge per wake interval** (151 edges/s at
the 1000-tick period) — the edge detector itself is not the limit: a pulse as short as the harness can
make it (~30 ns requested) still latched.

Board: ESP32-S3 rev v0.2, MAC `xx:xx:xx:xx:xx:xx`, flashed over `/dev/ttyACM1` (UART0).
Image flashed: `p18_gpio_edges.bin`, `sha256 ef91bbbf…4ba463` (`image.sha256`), `flash_args` in this
directory. One run, one image, no second attempt.

## 1. Answers

Set-up as measured: ULP armed on the RTC timer **only**, period requested 1000 ticks (6 460 µs),
no GPIO wakeup anywhere in the image. Real period from the harness:
`RATE 1Hz span_us=1 500 003 / 227 wakes` = **6 608 µs = 1 023 ticks** (+2.3 % over the request).
GPIO4 pad in the **RTCIO mux**, driven from the HP by writes to `RTCIO OUT_W1TS/OUT_W1TC`
(`s_digital_drive=0`), RTC-IO any-edge detect on pin 4, **no CPU interrupt routed** — the latch is
polled by the ULP, exactly the P06 fallback under test.

### Coalescing — N edges driven inside one wake interval

| N edges during sleep | status bits seen | events counted | interpretation |
| --- | --- | --- | --- |
| 2 | 1 (GPIO4, bit 14) | **1** | k edges → 1 event |
| 5 | 1 | **1** | k edges → 1 event |
| 50 | 1 | **1** | k edges → 1 event |
| 500 | 1 | **1** | k edges → 1 event |
| 5 000 | 1 | **1** | k edges → 1 event |

`COALESCE …, events=1, wakes=2, hits=1, status=0x00000000` for all five: one of the two wakes after
the burst had the bit set, the second (post-clear) wake read the raw status word as **0**. The status
is one bit per pin, so `k → 1` is structural, but it is now measured up to 5 000 edges.

### Rate sweep

| rate | edges sent | events observed | lost (not separately visible) | wake intervals spanned | lossless? |
| --- | --- | --- | --- | --- | --- |
| 1 Hz | 3 | 3 | 0 | 227 | **yes** |
| 100 Hz | 200 | 151 | 49 | 151 | no |
| 10 kHz | 1 000 | 7 | 993 | 7 | no |
| 100 kHz | 1 000 | 1 | 999 | 3 | no |

`events == wake intervals spanned` in every saturated case: the ceiling is **one event per pin per
wake**. Maximum non-losing edge rate at a 1000-tick period = 1 / 6.608 ms = **151 edges/s**
(2 edges/s measured lossless, 200 edges/s measured lossy — the boundary is between them, at 151).

Pulse width is not the limit: a single pulse latched at
100 µs, 30 µs, 10 µs, 3 µs, 1 µs, 300 ns, 100 ns and 30 ns requested
(`WIDTH ns=… events=1` for all eight; the real width is ≥ requested + store latency, so ~30 ns is the
harness floor, not the hardware's).

### Edge → wake latency

| phase offset after wake | measured latency | HP observation delay |
| --- | --- | --- |
| 0 µs | 6 592 µs | 3 µs |
| 800 µs | 5 790 µs | 802 µs |
| 1 600 µs | 4 988 µs | 1 601 µs |
| 2 400 µs | 4 188 µs | 2 402 µs |
| 3 200 µs | 3 391 µs | 3 202 µs |
| 4 000 µs | 2 588 µs | 4 002 µs |
| 4 800 µs | 1 789 µs | 4 802 µs |
| 5 600 µs | 990 µs | 5 602 µs |

`LATENCY n=8 min=990 med=4188 p95=6592 max=6592` µs. Latency = **period − edge phase**, i.e. it is
uniform over `[0, 6.6 ms]` and **never exceeds one period** (max 6 592 µs = 0.997 period). No edge was
lost in these trials (`LOST` never printed). The HP's own observation of a wake lags it by 1–3 µs
(`obs_delay_us`), and 1 000 reads of a ULP word cost 3 µs (`POLL`), so the polling harness adds ~µs,
not ms, of bias.

### Latch survival and clearing

* **Survives:** every trial's post-burst wake found the bit set after the edge had been driven while
  the ULP was asleep (`hits=1` in all 5 coalescing trials, `events=1` in all 8 width trials).
* **Clears:** `CLEAN quiet_wakes=3 events=0 hits=0` — three consecutive wakes with no new edge after
  the ULP's clear reported zero. `LATCH final_events=186 final_status=0x00000000` — the raw status
  word the ULP last sampled is 0, i.e. GPIO4's bit (and every other pin's) is clear.

## 2. Evidence

Files in this directory: `main/p18_gpio_edges_main.c` (HP), `main/ulp/main.c` (ULP),
`build.log`, `chipid.log`, `flash.log`, `capture.log`, `run.log`, `capture_g.py`, `p18_gpio_edges.bin`,
`image.sha256`, `flash_args`, `env.sh`, `sdkconfig*`.

Commands, in order:

```sh
# board lock + ESP-IDF (env.sh holds fd 9 on probe/results/.board.lock for the whole session)
timeout 30  bash -c '. ./env.sh && esptool -p /dev/ttyACM1 chip-id'                       # chipid.log
timeout 300 bash -c '. ./env.sh && idf.py build'                                          # build.log
timeout 30  bash -c '. ./env.sh && cd build && esptool -p /dev/ttyACM1 -b 460800 write_flash @flash_args'   # flash.log
timeout 20  bash -c '. ./env.sh && python3 capture_g.py /dev/ttyACM1 run.log'             # run.log
```

`chipid.log`: `Connected to ESP32-S3 on /dev/ttyACM1 … revision v0.2 … Hard resetting via RTS pin.`
`flash.log`: `Hash of data verified.` for bootloader, app and partition table.
`build.log` tail: `p18_gpio_edges.bin binary size 0x37aa0 bytes` … `Project build complete.`

`run.log`, complete:

```
P18 READY stage=console — send 'g' on UART0 (115200) to start
P18 GO gate=timeout

[capture] sent 'g' at t+0.15s
ULP running period_us=6460 wake_count=3
COALESCE n=2 events=1 wakes=2 hits=1 status=0x00000000
COALESCE n=5 events=1 wakes=2 hits=1 status=0x00000000
COALESCE n=50 events=1 wakes=2 hits=1 status=0x00000000
COALESCE n=500 events=1 wakes=2 hits=1 status=0x00000000
COALESCE n=5000 events=1 wakes=2 hits=1 status=0x00000000
WIDTH ns=100000 us=100 events=1
WIDTH ns=30000 us=30 events=1
WIDTH ns=10000 us=10 events=1
WIDTH ns=3000 us=3 events=1
WIDTH ns=1000 us=1 events=1
WIDTH ns=300 us=0 events=1
WIDTH ns=100 us=0 events=1
WIDTH ns=30 us=0 events=1
RATE 1Hz sent=3 events=3 lost=0 span_us=1500003 wakes=227
RATE 100Hz sent=200 events=151 lost=49 span_us=1000082 wakes=151
RATE 10kHz sent=1000 events=7 lost=993 span_us=50339 wakes=7
RATE 100kHz sent=1000 events=1 lost=999 span_us=5363 wakes=3
LAT off_us=0 lat_us=6592 obs_delay_us=3
LAT off_us=800 lat_us=5790 obs_delay_us=802
LAT off_us=1600 lat_us=4988 obs_delay_us=1601
LAT off_us=2400 lat_us=4188 obs_delay_us=2402
LAT off_us=3200 lat_us=3391 obs_delay_us=3202
LAT off_us=4000 lat_us=2588 obs_delay_us=4002
LAT off_us=4800 lat_us=1789 obs_delay_us=4802
LAT off_us=5600 lat_us=990 obs_delay_us=5602
CLEAN quiet_wakes=3 events=0 hits=0
PERIOD ulp_cyc_med=3 ticks_med=0 us_med=0
LATENCY n=8 min=990 med=4188 p95=6592 max=6592
LATCH final_events=186 final_status=0x00000000 wakes=480 digital_drive=0
P18 done ulp_stopped=1 pin=low latch_cls=0

[capture] end t+3.32s sent_g=True bytes=1509
```

Two evidence gaps, named rather than papered over:

1. **`P18 BOOT` / `SELFTEST` lines are missing from `run.log`.** The capture opened the port after
   the post-flash boot had already printed them and after the 8 s `g` gate had expired (`gate=timeout`),
   so the head of the log is the tail of that boot. The pad path is still pinned down by the run itself:
   `digital_drive=0` means `gpio4_setup_rtc()` found its rising edge latched (its return value gates the
   digital fallback), and the RTC-mux drive then latched on every one of the 13 subsequent trials.
   What is *not* measured is the printed A/B line for the digital-mux fallback — it was never taken.
   Answering P16's open question in the direction that matters: **an RTC-mux pad driven from RTCIO
   `OUT_W1TS/W1TC` by the HP does set the RTC-IO latch and is seen by the RTC-IO input** — P16's
   `isr_count=0` was the *routed interrupt* path, not the latch.
2. **`PERIOD ulp_cyc_med=3`.** The ULP's `rdcycle` delta between consecutive wakes is ~3 cycles, not
   the ~122 600 a 1 023-tick sleep should give, so the ULP cycle counter restarts at each wake and is
   **not** a cross-wake time base. The period and the latency table therefore come from HP timestamps
   (`esp_timer_get_time()`), and the two agree (`1 500 003 µs / 227 wakes = 6 608 µs`, and
   `latency = 6 592 µs − offset ± 2 µs`, i.e. one period).

## 3. Verdict

**PASS**, against the brief's pass criteria:

* **latches proven to survive sleep** — 13/13 trials found GPIO4's bit set at the wake after edges
  driven during the ULP's sleep, with the raw status word `0x00000000` at every post-clear wake;
* **coalescing rule as a number** — *k* edges inside one wake interval → **1** event, for
  k ∈ {2, 5, 50, 500, 5 000};
* **maximum non-losing rate** — **1 edge per wake interval = 151 edges/s** at a 1000-tick (6 608 µs)
  period; 3 edges at 1 Hz lossless, 200 edges over 1 s lossy (49 coalesced);
* **latency with a distribution** — `min 990 / med 4 188 / p95 6 592 / max 6 592 µs`, uniform over one
  period, never more than one period;
* **latch provably cleared between wakes** — `CLEAN quiet_wakes=3 events=0 hits=0`.

Failure branches, checked against the criteria:

* *Latches do not survive sleep* — **not** the case; no change of owner for pin events.
* *Only one edge is visible per sleep (level, not edge)* — **this is the case and it is the design
  consequence**: the ring's contract is "one latched event per pin per wake", so a pin that sees two
  edges inside one period is indistinguishable from one, and above 151 edges/s the count is lost while
  the *fact* of activity is never lost. §5's wording must say "level since last wake", not "edge".
* *Edges lost above some rate* — yes, at 151 edges/s (coalescing, not detector blindness: a lone 30 ns
  pulse still latches).
* *Latency > one period* — no; 0.997 period worst case, so attribution is safe, but an event's
  timestamp is "somewhere in the last period" (≤ 6.6 ms of ambiguity) and R3's item must say so.

## 4. Doc deltas

**`docs/01-proposal.md`: §5 → the "Wake cause is not readable" bullet.**

Old (verbatim, wrapping as in the file):

```
  wake** and coalesces: one event per pin per wake, counted, no timestamps. That is weaker than
  "timestamped edges" and it is what the hardware offers.
```

New:

```
  wake** and coalesces: one event per pin per wake, counted, no timestamps. Measured (P18): the latch
  survives the ULP's sleep, *k* edges inside one wake interval set the pin's single status bit and are
  reported as exactly **1** event (k = 2, 5, 50, 500, 5 000 all → 1), the ULP's clear leaves the latch
  at 0 on the following wake, and a pulse as short as ~30 ns still latches. So the rule is **k edges →
  1 event, at most one event per pin per wake**: the ceiling is 1/period = **151 edges/s at a 1000-tick
  (6.61 ms) period**, and above it the count is lost while the fact of activity never is. An edge is
  reported within the period it falls in: latency measured 990–6 592 µs (median 4 188 µs), uniform over
  one period, never more than one. The ring's contract is therefore **level since last wake, not edge
  count** — a pin that toggles twice inside one period is indistinguishable from one toggle, and the
  event carries no sub-period timestamp.
```

**`docs/01-proposal.md`: §10 R3 → the GPIO item.**

Old (verbatim):

```
- [ ] A GPIO edge produces exactly one coalesced event per pin per wake, handled in the same wake or
      the next — never lost, never duplicated. **No timestamps:** the wake-cause register reads 0 on
      every wake (P06), so cause comes from polling RTC-IO status.
```

New:

```
- [x] A GPIO edge produces exactly one coalesced event per pin per wake, handled in the same wake or
      the next — never lost, never duplicated. **No timestamps:** the wake-cause register reads 0 on
      every wake (P06), so cause comes from polling RTC-IO status. **Measured (P18):** latch survives
      sleep (13/13 trials), k edges in one period → 1 event (k up to 5 000), latch reads 0 after the
      ULP clears it, edge → event latency 990–6 592 µs over one 6.61 ms period (median 4 188 µs).
      Limits to publish: **151 edges/s per pin at a 1000-tick period** (= one event per wake, so it
      scales as 1/period), a pulse floor below ~30 ns only (detector is not the limit), and the event
      is *level/activity since last wake*, not an edge count — bursts above the rate lose the count,
      never the occurrence.
```

## 5. Follow-ups

* **Does the RTC-IO latch survive *deep* sleep (HP off), or only light/ULP sleep?** This run kept the
  HP awake to drive the pin; if the pin is driven by an external source through a real deep sleep, does
  the pad keep its input enable and does the latch survive the HP's power-down (`RTCIO` domain is
  powered, but `fun_ie`/`slp_ie` are a separate field)? Needs an external edge source or a second pad.
* **What is the true minimum pulse width?** Every width the harness could generate (~30 ns and up)
  latched, so the floor is below the harness, not measured. A ULP-driven or hardware-timed pulse
  generator would put a number on it — but only matters if an input can be that fast.
* **Why does 1000 ticks request 6 460 µs and produce 6 608 µs (+2.3 %)?** `ulp_set_wakeup_period()`'s
  tick conversion vs the P05 calibration constant; R3's "wake_count matches elapsed/period within 1 %"
  item is not met at 2.3 % if this is real.
* **Does `rdcycle` restart on every ULP wake (measured delta ≈ 3 cycles)?** If so, the ULP cannot
  timestamp across wakes and the event ring cannot carry even a coarse tick count — the "no timestamps"
  clause of §5 becomes a hardware fact rather than a choice.
* **Where do the RTC-IO driver paths differ: latch vs routed interrupt?** P16 saw `isr_count=0` for the
  routed interrupt on GPIO4 in both muxes while this run's latch set on every edge. Which mask/routing
  register is missing, and does the routed interrupt become the cheap event path?
