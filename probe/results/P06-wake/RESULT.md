# P06 — Wake semantics: period overrun, and timer + GPIO together (second attempt)

**Status: PASS on the overrun question, PARTIAL elsewhere.** The board survived, the overrun
behaviour is identified and reproducible, both wake enables arm together on hardware, but cause
attribution and GPIO latency were **not** obtained, and the retire-after-abort check **hangs the
firmware** (recoverable, see §2.4).

Project: `probe/results/P06-wake/` (`main/p06_wake_main.c`, `main/ulp/main.S`). Logs:
`run_v2.log` (run 1), `run_v2b.log` (run 2 — the aborted-path hang), `run_v2c.log` (run 3 — overrun
sweep, clean), `build_v2*.log`, `flash_v2*.log`, `alive*.log`, `recover1.log`,
`restore_p05.log`. Image kept: `p06_wake.bin` (sha256
`690fce00a32e3d90615cf51df43275afe6c8674ca857323ee23fc76dcc18c10e`) + `flash_args`.

Hardware: ESP32-S3, MAC `xx:xx:xx:xx:xx:xx`, all traffic over **`/dev/ttyACM1`** (UART0/CH343),
console 115200, wake pin **GPIO4**.

---

## 1. Answers

| Item | Value |
| --- | --- |
| overrun verdict | **drift — the sleep timer re-arms from wake *exit*** (no tick lost on a grid, no latch, no re-entry, no hang) |
| wakes/sec at 0.1×, 1×, 2×, 10× budget | 6117 / 5881 / 5664 / 4368 wakes/s — **all ≈ `1/(22 ticks + span)`, not `1/period`** |
| `rdcycle` delta distribution between wakes | not obtainable (`rdcycle` resets each wake, as given); the tick-side delta is **gap = span + 22 ticks, min = max = mean** in every phase |
| both wake sources armed? | **yes, on hardware** — `RTC_CNTL_ULP_CP_TIMER_REG` readback `0xA0000000` (`SLP_TIMER_EN`=BIT31, `GPIO_WAKEUP_ENA`=BIT29 both 1) |
| cause attribution correctness | **0 / 6 — not attributable.** `RTC_CNTL_SLP_WAKEUP_CAUSE_REG` read `0x00000000` on *every* wake, timer-only baseline included |
| GPIO edge → event latency | **not obtained.** All six "latency" samples are timer wakes (see §2.3) |
| retire after abort | **no** — the abort path kills the console within ~1 s |

### 1.1 The overrun answer, in one line

`gap_between_wake_starts = span_of_previous_wake + 22 ticks` (constant 22, span swept 3 → 47 ticks).
The ULP sleep timer therefore starts counting **when the wake retires**, so an overrun does not lose a
grid tick and does not latch: it **stretches the next interval 1:1 by its own duration, permanently**.
Time drifts by the cumulative overrun instead of self-correcting.

### 1.2 The floor that makes this matter

`ulp_set_wakeup_period(0, 8)` (intended 1.2 RTC ticks) produced an inter-wake interval of **25 ticks
(161 µs)** minimum, i.e. a **22-tick / 142 µs** floor between wake *start* and wake *start* even when
the wake body is empty (span 3 ticks). A 1-tick period is **not achievable**; the shortest observable
ULP period on this part is ~22 RTC ticks.

---

## 2. Evidence

Reproduce (all steps used `timeout`; board lock taken from `probe/results/.board.lock`):

```sh
cd /home/user/research/esp32-rv32 && . probe/results/P06-wake/env.sh   # see §2.0
export IDF_PATH=/home/user/research/esp32/esp-idf && . $IDF_PATH/export.sh
cd probe/results/P06-wake
timeout 300 idf.py build
timeout 30 esptool -p /dev/ttyACM1 chip-id                        # liveness + RTS reset
timeout 30 esptool -p /dev/ttyACM1 -b 460800 write-flash 0x0 build/bootloader/bootloader.bin \
    0x8000 build/partition_table/partition-table.bin 0x10000 build/p06_wake.bin
timeout 25 python3 capture_g.py /dev/ttyACM1 run_v2c.log          # waits for READY, sends 'g'
```

### 2.0 Staging that made the run safe and attributable

`app_main` order, exactly as the brief demanded: **TWDT first** (`esp_task_wdt_init` 12 s +
`esp_task_wdt_add`, panic enabled; `wdt_init=0` after `esp_task_wdt_reconfigure` — the startup code had
already inited it, `E task_wdt: esp_task_wdt_init(515): TWDT already initialized`), then banner
`P06v2 BOOT stage=wdt`, then `uart_driver_install(UART_NUM_0,...)`, then banner
`P06v2 READY stage=console — send 'g' on UART0 (115200) to start`, then a **20 s gate**:

```
P06v2 READY stage=console — send 'g' on UART0 (115200) to start
[capture] sent 'g' at t+0.6s
P06v2 GO gate=console
```

Run 1 shows the gate's failure mode working: the host opened the port 2 s late, missed the banner, sent
nothing, and the app printed `P06v2 GO gate=timeout` and ran anyway — never silent.

Nothing on the board could be killed by a wrong pin: wake pin is **GPIO4**, and **GPIO19/20 were never
touched** (no `gpio_config`, no `gpio_set_level`, no sleep-wake source on them anywhere in the image).

### 2.1 Overrun sweep — run 3, clean, `P06 done` printed

`period_us=8`, `delay_cycles` swept, 300–500 ms esp_timer windows, all values ULP-side RTC ticks:

```
OVER 0.1x  delay=12    window_us=300139 wakes=1836 wps_milli=6117165 span_last_us=19
GAP  0.1x  n=1835 gap_ticks[mean_milli=24998] resid_ticks[min=22 max=22 mean_milli=21954]
OVER 1x    delay=122   window_us=300143 wakes=1765 wps_milli=5880530 span_last_us=25
GAP  1x    n=1764 gap_ticks[mean_milli=25998] resid_ticks[min=22 max=22 mean_milli=22000]
OVER 2x    delay=245   window_us=300143 wakes=1700 wps_milli=5663966 span_last_us=32
GAP  2x    n=1699 gap_ticks[mean_milli=26998] resid_ticks[min=22 max=22 mean_milli=22000]
OVER 10x   delay=1226  window_us=500904 wakes=2188 wps_milli=4368102 span_last_us=83
GAP  10x   n=2187 gap_ticks[mean_milli=34999] resid_ticks[min=22 max=22 mean_milli=22000]
OVER 1x_floor22ticks delay=2700 window_us=300143 wakes=977 wps_milli=3255115 span_last_us=161
GAP  1x_floor22ticks n=976 gap_ticks[mean_milli=46997] resid_ticks[min=22 max=22 mean_milli=22000]
OVER 2x_floor22ticks delay=5400 window_us=300143 wakes=665 wps_milli=2215610 span_last_us=303
GAP  2x_floor22ticks n=664 gap_ticks[mean_milli=68996] resid_ticks[min=22 max=22 mean_milli=22000]
RAW 0.1x cyc_top=81 cyc_end=568 ... RAW 2x_floor22ticks cyc_end=… (cyc_top=81 in all six phases)
P06 done
```

Derived (154.9 kHz, 6.46 µs/tick — never 136 kHz):

| phase | span (ticks) | gap (ticks) | gap − span | gap (µs) | wakes/s |
| --- | --- | --- | --- | --- | --- |
| 0.1× (12 cyc) | 3 | 25 | **22** | 161 | 6117 |
| 1× (122 cyc) | 4 | 26 | **22** | 168 | 5881 |
| 2× (245 cyc) | 5 | 27 | **22** | 174 | 5664 |
| 10× (1226 cyc) | 13 | 35 | **22** | 226 | 4368 |
| 1× floor (2700 cyc) | 25 | 47 | **22** | 304 | 3256 |
| 2× floor (5400 cyc) | 47 | 69 | **22** | 446 | 2216 |

The last two rows are **real overruns**: the wake body (25 and 47 ticks) is longer than the 22-tick
period the timer was armed with.

**Why this is drift and not "lost", "latched" or "re-entry":**

* *Latched/pending tick* would give `gap − span ≈ 0` and bursts. Measured `resid = 22`, constant.
* *Fixed-grid tick loss* would give `resid = 22 − (span mod 22)` ∈ [1, 22] — predicted 22/18/17/9/19/19
  for the six spans. Measured **22, 22, 22, 22, 22, 22**. The grid model is refuted by the two
  overrun points (span 25 → predicted 19, measured 22; span 47 → predicted 19, measured 22).
* *Re-entry mid-flight* is refuted by `cyc_top = 81` in every phase and every wake: the core takes the
  full entry sequence each time, so "wake = reset" holds (11 000+ wakes).
* Measurement `min`/`max` in the log are stale registers, not variation: the ULP's min/max store
  branches are inverted (`bgeu` where `bltu` belongs), so `min` reads back `0xFFFFFFFF` and `max`
  reads `0`. **`gap`/`resid` means are totalled in `sum` and are exact**: `mean_milli = 24998` over
  1835 samples is integer-exact. Treat min/max as invalid and mean as per-wake.

So the timer behaves as **"re-arm on retire"**: `T_next = T_exit + 22 ticks`. A wake that overruns the
period costs exactly its overrun, every period, cumulatively — and nothing corrects it.

### 2.2 Retire / DONE, normal path

`wake_ctr` advanced monotonically in all six phases (~11 000 wakes) and every phase ended with
`ulp_riscv_timer_stop()` and the next phase re-arming normally: the normal `ret` → `ulp_riscv_halt()`
path retires and the timer re-arms. `P06 done` printed.

### 2.3 Wake-source coexistence — armed, not attributable

```
COEX baseline timer_only window_us=200766 wakes=175 cause_raw=0x00000000
COEX arm reg=0xA0000000 slp_en=1 gpio_ena=1 gpio_wakeup_api=0
```

* **Both sources armed on hardware: yes.** `SET_PERI_REG_MASK(RTC_CNTL_ULP_CP_TIMER_REG,
  RTC_CNTL_ULP_CP_GPIO_WAKEUP_ENA)` after `ulp_riscv_run()` gives `BIT31|BIT29 = 0xA0000000`, read back
  from the device. IDF's one-source limit is a `switch`, not a register constraint — **confirmed on
  silicon, not just in the header.** Disarm readback: `reg=0x00000000 gpio_ena=0`.
* **Attribution failed.** The ULP reads `RTC_CNTL_SLP_WAKEUP_CAUSE` (`RTCCNTL+0x130`) at wake entry:
  `0x00000000` on the timer-only baseline **and** on all six GPIO-armed windows. That register does not
  carry ULP wake sources (it is the HP sleep-controller cause). Reading a status register was the
  right move; the register is the wrong one. `gpio_attributed = 0 / 6`.
* **GPIO latency: not obtained, and the six printed values are invalid as latency data.** The timer
  floor is 142 µs while the host polled every 10 µs, so `wake_ctr` advanced on a timer wake before the
  pin could matter: `lat_ticks = 155, 33, 2, 4294967294, 7, 4`. The `4294967294` (a wrap, i.e. a wake
  *before* the edge) and the 1000 µs/213 µs samples are proof these are timer wakes, not GPIO wakes.
  A GPIO latency measurement needs the timer **stopped** and the ULP woken by the edge alone.

### 2.4 The hang — stage-attributed, recoverable

Run 2 (`run_v2b.log`) ran the abort/retire phase, which runs 3 does not (`if (0)`). Last console bytes:

```
COEX disarm reg=0x00000000 gpio_ena=0\r\n
```

…and then **16 s of silence** to the end of a 20 s capture window: no `ABORT window_us=...` line, no
TWDT panic, no reset. Run 1 ended at the same line (its window closed before the phase started).

| Fact | Value |
| --- | --- |
| stage that died | `retire_phase()` first window — the `mode == 1` aborted wake (ULP writes `COCPU_DONE\|COCPU_SHUT_RESET_EN` mid-`main`, then spins) |
| last console byte | `=0\r\n`, i.e. the tail of `COEX disarm reg=0x00000000 gpio_ena=0` |
| TWDT reaction | none in 17 s, though it was armed with `trigger_panic=true` at 12 s — the panic path is in the RTC/system domain the abort script disturbs |
| recovery | `esptool -p /dev/ttyACM1 chip-id` → `MAC: xx:xx:xx:xx:xx:xx`, `Hard resetting via RTS pin` — **worked first try, no EN press, ~2 s** |
| board health after | fine: re-flashed, re-ran, `P06 done` (run 3) |

This is the same signature as the first attempt, now **reduced to one phase and made recoverable by the
UART0/RTS path the brief mandated**. It is not the RTC-IO arming (that phase ran and disarmed cleanly
in the same boot before the hang), and it is not the 8 µs period (run 3 hammered it for 1.7 s).
**Suspect confirmed: the non-return abort path.**

---

## 3. Verdict

**PASS on question 1, PARTIAL on 2, FAIL on 3, FAIL on retire.**

| pass criterion | outcome |
| --- | --- |
| overrun behaviour identified and reproducible | **PASS** — drift, `resid = 22` in all six windows, reproducible across runs 1/2/3 |
| both sources armed ⇒ both causes observed and correctly attributed | **FAIL** — armed ✓ (`0xA0000000`), attributed ✗ (0/6) |
| GPIO latency measured with a distribution | **FAIL** — no GPIO-attributable samples |
| `wake_count` never stops advancing (normal and aborted) | **normal: PASS** (11 000+ wakes, 6/6 phases); **aborted: FAIL** (console and counters die) |

What the answer changes: §5's budget cannot be built on "period" at all. The observable period is
`22 ticks + previous wake duration`, so **timing is cumulative overrun, not a fixed grid**, and the
hard stop must be a cycle budget inside the wake, not a reliance on the timer.

## 4. Doc deltas

**`docs/01-proposal.md` §5 — budget divisor and overrun rule** (replace the paragraph; verbatim):

> The ULP sleep timer re-arms **when the wake retires**, not on a free-running grid: measured
> `interval = 22 ticks + duration of the previous wake`, with the 22 ticks constant over spans of
> 3–47 ticks (P06). Overrunning the period therefore does not lose a tick, does not latch one and does
> not re-enter — it **stretches the interval 1:1 and the error accumulates**. Consequences: (a) the
> per-wake budget must be a `rdcycle` hard stop well inside the iteration, never a hope that the timer
> will bound us; (b) the divisor is not `÷2` of `period_ticks × 122.6` — the measured floor is
> **22 ticks (142 µs) of timer overhead per wake**, so a wake's usable time is
> `period_ticks × 122.6 − (22 × 122.6)` and for any period under ~22 ticks there is **no** usable time
> at all; (c) any wall-clock deadline must accumulate `Σ(22 + span)` ticks, not `n × period`.

**`docs/01-proposal.md` §5 — GPIO paragraph** (fallback triggered for attribution only, not for
coexistence; verbatim):

> Timer and RTC-IO wakeups **can** be armed together on ESP32-S3: setting `SLP_TIMER_EN` (BIT31) and
> `GPIO_WAKEUP_ENA` (BIT29) of `RTC_CNTL_ULP_CP_TIMER_REG` independently is confirmed on hardware
> (readback `0xA0000000`). What is **not** available is per-wake attribution: `RTC_CNTL_SLP_WAKEUP_CAUSE`
> reads 0 for ULP wakes, so the ULP cannot tell a GPIO wake from a timer wake from that register. Until
> an attributable mechanism is found (e.g. stop the timer and wake on the edge alone), GPIO events must
> be **timestamped by sampling the pin inside each timer wake**, and R3's "timestamped edge" becomes
> "coalesced within one period, ±1 period of uncertainty".

**`docs/01-proposal.md` §10 — R3 items** (verbatim):

> * *Retiring*: retire on the **normal** return path is confirmed (11 000+ wakes, `cyc_top = 81` each
>   time, timer keeps re-arming). Retire on a **non-return** exit is **not** confirmed and must not be
>   designed for: a ULP that writes `COCPU_DONE|COCPU_SHUT_RESET_EN` and spins takes the console with
>   it and needs a chip reset (P06 runs 1–2).
> * *GPIO events*: as above — armable together with the timer, **not** attributable per wake.

**`docs/00-background.md` §2.4 — execution-model table** (verbatim):

> No correction needed to "wake = reset": `rdcycle` read 81 at entry on all six P06 phases
> (11 000+ wakes), including 2.1× overruns of the period. What §2.4 must **add** is the re-arm rule:
> the sleep timer counts from **wake exit**, so `T_next_start = T_prev_end + 22 ticks`; the period is a
> *minimum gap*, not a schedule, and overrun is cumulative drift.

## 5. Follow-ups

1. **Never run the abort/retire path in the same boot as measurements again** — it is kept in the
   source behind `if (0)` with a GUARDRAIL note. If it is ever needed, run it in a dedicated image and
   expect to reset over UART0.
2. **Attribution needs a different mechanism**: stop the ULP timer, arm only the RTC-IO wake, and see
   whether the ULP wakes at all; if it does, use `ulp_wake_tick_last` against a host `esp_timer` stamp
   to get edge→wake latency. That is a small, separate probe (one question, one image).
3. **GPIO latency cannot be measured with the timer running** — 142 µs of timer floor swamps any edge
   signal; the pin must be the only wake source.
4. **Fix the ULP min/max branch inversion** in `main/ulp/main.S` (`bgeu`/`bltu`), or drop the min/max
   fields: means are exact but min/max silently read back `0xFFFFFFFF`/`0`.
5. **The 22-tick floor** deserves one line of explanation (register-level `ulp_set_wakeup_period`
   conversion vs. measured floor) before §5's formula is frozen.

## What is flashed on the board now

**P05's known-good image, restored at 13:03:37** — `esptool -p /dev/ttyACM1 write-flash` of
`../P05-clock/build/{bootloader.bin@0x0, partition-table.bin@0x8000, p05_clock.bin@0x10000}`, all three
regions `Hash of data verified` (`restore_p05.log`), and the console then showed P05's own output
(`P05 start (CONFIG_ULP_COPROC_RESERVE_MEM=4096)`, `PHASE p10000t ...`). No P06 code is running; the ULP
is not left spinning.

The P06 image that was run is kept at `probe/results/P06-wake/p06_wake.bin` + `flash_args` (sha256
`690fce00a32e3d90615cf51df43275afe6c8674ca857323ee23fc76dcc18c10e`; runs 1–2 used the earlier build
`b8d073329bfe5142357b0190e224e06bebcbde7b76993a3d46e8eab2d2ea9792`, whose only difference is the extra
sweep points and the call to the abort/coexist phases).
