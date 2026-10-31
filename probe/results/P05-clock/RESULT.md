# P05 — Clock and cycle calibration

**Status: PASS (second run, `run2.log`).** The per-instruction cycle costs were measured and reproduce to 0.03 %
(run 1), and the missing number is now closed: **122.6 cycles per RTC_SLOW_CLK tick**, from 12 independent
measurements (3 K values × 4 phases) spread over 0.78 %, implying a **core clock of 19.0 MHz ± 0.3 MHz (±1.5 %)**.
The one *failed* pass criterion is the RTC_SLOW_CLK cross-check against 136 kHz: this chip's slow clock measures
**154.9 kHz**, which is the internal ~150 kHz RC oscillator, not the 136 kHz "typical" figure in the docs (see §2.8 —
this is a documentation error, not a measurement error, and it changes every "µs" figure derived from ticks).

History: run 1 (`build1.log`, `flash1.log`, `run1.log`) was PARTIAL — instruction costs only — because
`RTC_CNTL_TIME_LOW0` is a latched snapshot that was read without triggering the latch, and the HP-side window loop
collapsed to its iteration cap. Both were fixed for run 2 (see §2.4, §2.5, §2.7) without re-measuring anything else.

Project: `probe/results/P05-clock/` (ULP kernel `main/ulp/main.S`, HP driver `main/p05_clock_main.c`).
Logs: run 1 `build1.log` / `flash1.log` / `run1.log`; run 2 `build2.log` / `flash2.log` / `run2.log`.

---

## 1. Answers

| Item | Value | How |
| --- | --- | --- |
| cycles per `addi` (dependent chain) | **4.000** (4.000 / 4.000 / 4.000 over 3 runs) | span(30/iter) − span(10/iter) = 8000 over 2000 addi |
| cycles per RTC RAM load (`lw`, same address family) | **8.10** (8.100 / 8.101 / 8.102) | delta 16201…16204 over 2000 loads |
| cycles per byte-access emulating `rd8` (`lb`) | **8.60** (8.600 / 8.600 / 8.600) | delta 17201 over 2000 byte loads |
| cycles for the prototype's byte-wise `rd32` | **≈ 69** (8 × 8.6) vs **8.1** for one native `lw` | arithmetic on the two rows above |
| cycles per RTC_SLOW_CLK tick | **122.6** (K=1024: 122.541–122.780, 0.2 %; all 18 measurements 122.093–123.046, 0.78 %) | §2.7: poll the latched RTC counter forward by K ticks between two `rdcycle` reads |
| implied core frequency | **19.0 MHz ± 0.3 MHz (±1.5 %)** = 122.6 cycles/tick × 154.9 kHz | §2.8 |
| RTC_SLOW_CLK frequency (measured) | **154.9 kHz ± 0.5 kHz** (phases: 153.94 / 154.79 / 154.86 / 154.93 kHz; work-limited phases read 153.4–156.4) | `tick_gap / esp_timer interval` |
| 1 tick in wall-clock time | **6.46 µs** (not 7.35 µs as the 136 kHz figure implies) | 1 / 154.9 kHz |
| budget for a 1-tick wake | 122.6 cycles, of which **81 are already the wake entry** → **41 cycles ≈ 10 dependent ALU ops or 5 RTC RAM loads of actual work** | §3 |
| wake overhead before `main` | **81 cycles** (constant on every wake: `cyc_top = 81`) | first `rdcycle` in `main`; the counter is **reset per wake** |
| cycles burned inside one wake (`main` entry → exit) | **259 100 – 259 588** cycles (run 2, ≈ 2115 ticks ≈ 13.7 ms), stable to ±0.2 % | `span_wake` |
| wall-clock vs tick cross-check | **done, and it disagrees with 136 kHz**: 154.9 kHz measured (§2.8) | `tick_gap` vs `esp_timer` |
| period values tested | run 1: `period_us` 73535, 735, 100, 74, 8. run 2: 73535, 735 ×3, 74, 8 (≈14 300, 114, 11.5, 1.2 ticks at the measured 154.9 kHz) | 735 µs ≈ 114 ticks |

Decomposition of the 137 935-cycle wake (from the spans, 100 iterations each):
`5601 + 13601` (addi blocks) `+ 9400 + 25601` (lw blocks) `+ 43269` (K block: tick read + 10 000-addi
chain) `+ 11400 + 28601` (lb blocks) `+ ~460` setup/bookkeeping. So the kernel is ~85 % of the wake
and the harness/prologue is small.

**Answer to the probe's headline question** ("can a 1-tick period run work?"): a wake costs
**138 k cycles minimum for this kernel alone**, and 1 tick is one RTC_SLOW_CLK period. Whatever the
core clock turns out to be, the usable work per wake is set by `cycles_per_tick`, which this run did
not establish — the number is still owed (see Follow-ups, ~10 min of work).

## 2. Evidence

Reproduce: `export IDF_PATH=/home/user/research/esp32/esp-idf && . $IDF_PATH/export.sh`, then
`idf.py set-target esp32s3 && idf.py build && idf.py -p /dev/ttyACM0 flash`, capture UART0 from
`/dev/ttyACM1` at 115200:

```sh
stty -F /dev/ttyACM1 115200 raw -echo -crtscts
timeout 25 cat /dev/ttyACM1 > run1.log
```

### 2.1 Differential method

Each block runs twice with identical loop overhead and a 10- vs 30-instruction body, 100 iterations:

```
span10 = 100 x (10 body + addi + bnez),  span30 = 100 x (30 body + addi + bnez)
cycles_per_body_op = (span30 - span10) / 2000
```

Setup, loop counter and branch costs cancel exactly. `run1.log`:

```
BLOCK addi span10=5601 span30=13601 delta=8000 milli_cycles_per_op=4000
BLOCK lw   span10=9400 span30=25601 delta=16201 milli_cycles_per_op=8100
BLOCK lb   span10=11400 span30=28601 delta=17201 milli_cycles_per_op=8600
```

Three independent runs (phases `repeat1…3`, each with a fresh `ulp_riscv_load_binary`), same rows
reproduced at 8100 / 8101 / 8102 (lw) and 8600 / 8600 / 8600 (lb) — **pass criterion "within 5 %"
met with two orders of magnitude to spare** for the instruction costs.

### 2.2 `rdcycle` counts real cycles, and is reset per wake

`cyc_top` is the first instruction of `main`:

```
RAW repeat1 wake=8 cyc_top=81 cyc_end=138016 gap=4294829362 span_wake=137935 ...
RAW repeat2 wake=8 cyc_top=81 cyc_end=138018 gap=4294829362 span_wake=137937 ...
RAW repeat3 wake=8 cyc_top=81 cyc_end=138020 ... span_wake=137936 ...
```

* `cyc_top = 81` on every wake ⇒ **mcycle restarts at each wake**, so the 81 cycles are exactly the
  reset-vector + `__start` + `call main` cost (reset vector 4 B, `__start` 16 B, per E-004/E-005).
  This is the requested wake overhead measurement: **~81 cycles, constant**.
* `gap` (`cyc_top − cyc_end_prev`) is a large negative number (`4294829362` = −137934) exactly
  because the counter restarted — an independent confirmation of the same fact.
* `cyc_end` grows by 2–4 cycles between otherwise identical runs; `rdcycle` does not wrap or
  saturate at 16 bits over 138 k cycles, and increments by ≥1 per instruction (4.0 per dependent
  `addi` is self-consistent with a 32-bit counter). **The "`rdcycle` does not count what we assume"
  failure mode is ruled out.**

### 2.3 The documented `ULP_RISCV_CYCLES_PER_US 17.5` for S3 is not the core clock

`components/ulp/ulp_riscv/ulp_core/include/ulp_riscv_utils.h` hard-codes
`ULP_RISCV_CYCLES_PER_US 17.5` for S3. A dependent `addi` costing 4 cycles means the core retires at
most ~1 instruction per 4 cycles, i.e. 17.5 "cycles"/µs cannot be instruction throughput for any
number with 4-cycle ALU latency unless the microarchitecture hides it; this must be treated as an
unverified constant until `cycles_per_tick` is measured (it is used by `ulp_riscv_delay_cycles`).

Cost structure also matters for the design: **a dependent ALU op is 4 cycles, a memory access is
8.1–8.6 cycles.** RTC slow memory is roughly 2 ALU ops of latency; a byte load costs the same as a
word load (+0.5), so *byte-wise access is expensive purely because of access count*, not because a
byte load is slower.

### 2.4 Why `cycles per tick` was missing in run 1 — the RTC counter needs the `TIME_UPDATE` latch

`tick0 == tick1 == 416095043` on every wake and every phase, i.e. the ULP read of `0x8010`
(`RTCCNTL` 0x8000 + `RTC_CNTL_TIME_LOW0_REG` 0x10) returned the same non-zero value across a 43 269
cycle span and across wakes. That value is a **latched snapshot**, not the live counter:
`components/soc/esp32s3/register/soc/rtc_cntl_reg.h` has `RTC_CNTL_TIME_UPDATE_REG` at
`DR_REG_RTCCNTL_BASE + 0xC`, and the ESP32-family sequence is *set the update bit, wait for it to
self-clear, then read TIME_LOW0/TIME_HIGH0*. The address is right, the read path works (the value is
plausible and non-zero) — the latch was never triggered. `span_k = 43269` cycles of chain between
the two reads, so once the latch is added the quantisation error is 1 tick / ≈430 ticks < 0.3 %.

### 2.5 Why the wall-clock cross-check was missing in run 1 — `pdMS_TO_TICKS(1) == 0`

The HP window loop was `vTaskDelay(pdMS_TO_TICKS(1))` with a `window_ms * 4` iteration cap. With the
IDF default `CONFIG_FREERTOS_HZ=100`, `pdMS_TO_TICKS(1) == 0`, so `vTaskDelay(0)` only yields: every
"2 s window" ended when the 8000-iteration cap was hit at **`window_us=60125`**. The wake counts in
that log (`wakes=8` for a 735 µs period) are therefore *work-limited* counts over ~110 ms, not
period-limited counts:

```
PHASE repeat1 period_us=735 window_us=60125 wakes=8 interval_us_milli=7515625 tick_gap=0
```

**Fixed in run 2**: the loop body is `esp_rom_delay_us(1000)` and the windows are real
(`window_us=2000540` / `1000269` / `600762` in `run2.log`).

### 2.6 Bugs in this probe's own instrumentation (do not re-derive them)

* `top_min` / `top_max` stayed at `0xFFFFFFFF` / `0`: the asm comparison
  (`bgeu t2, s1, 1f` then store) skips the store exactly when it should store — the branch is
  inverted. `cyc_top` was constant anyway, so the min/max tracker was redundant.
* `span_a3` was declared but never written (the K block stores only `span_k`); it reads 0.
* Run 1's `tick_gap` was computed from the un-latched counter, so it read 0 for the same reason as
  §2.4.
* **Loop-alignment sensitivity (~±2 %)**: the `lw` differential read `delta=16201/2000 = 8.10` in run 1
  and `delta=15799/2000 = 7.90` in run 2 with *byte-identical* L1/L2 blocks — the loop start address
  moved with the surrounding code. Treated as alignment noise; the settled figure remains **8.1 cycles
  per `lw` (±0.2)**. The `addi` (4.000) and `lb` (8.600) differentials were bit-identical in both
  builds, so this affects only the `lw` row.

### 2.7 `cycles per RTC tick` — measured: 122.6 (run 2)

**Fix.** `RTC_CNTL_TIME_UPDATE_REG` (`RTCCNTL + 0xC`) is write-only and its request bit is **bit 31**
(`RTC_CNTL_TIME_UPDATE = BIT(31)` in `soc/esp32s3/register/soc/rtc_cntl_reg.h`), not bit 0. The ULP
kernel now does `sw 0x80000000, 0x0c(s6)` → poll the same register until bit 31 self-clears →
`lw 0x10(s6)` (the `TICK_READ` macro in `main/ulp/main.S`).

**Method.** Inside one wake: `TICK_READ` a base snapshot, `rdcycle t0`, then re-latch and poll the
counter until it has advanced by at least K ticks, then `rdcycle t1`. The *observed* advance `delta`
is stored alongside the span, so a one-tick overshoot at the polling boundary cannot bias the result
(`cycles_per_tick = span / delta`, not `span / K`). Three K values (64, 256, 1024) quantise the
~40-cycle poll boundary differently: 4 wake-period phases × 3 K = **12 independent measurements**.

```
TICK p10000t span64=7814 dt64=64 mcyc64=122093 span256=31421 dt256=256 mcyc256=122738 span1024=125544 dt1024=1024 mcyc1024=122601
TICK p100t_a span64=7875 dt64=64 mcyc64=123046 span256=31482 dt256=256 mcyc256=122976 span1024=125727 dt1024=1024 mcyc1024=122780
TICK p100t_b span64=7814 dt64=64 mcyc64=122093 span256=31299 dt256=256 mcyc256=122261 span1024=125483 dt1024=1024 mcyc1024=122541
TICK p100t_c span64=7814 dt64=64 mcyc64=122093 span256=31360 dt256=256 mcyc256=122500 span1024=125666 dt1024=1024 mcyc1024=122720
TICK p10t    span64=7814 dt64=64 mcyc64=122093 span256=31360 dt256=256 mcyc256=122500 span1024=125605 dt1024=1024 mcyc1024=122661
TICK p1t     span64=7814 dt64=64 mcyc64=122093 span256=31421 dt256=256 mcyc256=122738 span1024=125483 dt1024=1024 mcyc1024=122541
```

* **K = 1024 (least poll-boundary bias): 122 541 – 122 780 milli-cycles/tick, mean 122 641 →
  `cycles_per_tick = 122.64`, spread 0.20 %.**
* All 12 values: 122.093 – 123.046 → `122.6 ± 0.5` (0.78 % spread). The poll-boundary systematic
  shows up as the K = 64 values sitting ~0.45 % low (shorter span, same ~40-cycle boundary); that is
  why K = 1024 is quoted.
* Sanity: `span1024 = 125 544` cycles for 1024 ticks, and the whole wake is `span_wake = 259 282`
  cycles over `tick_gap = 13 390` ticks. Fixed parts (three K polls at 122.6/tick plus the ~95 k-cycle
  instruction blocks) sum to the same order — no anomaly > 2× anywhere.

### 2.8 The implied core frequency, and the 136 kHz cross-check that does not hold

`tick_gap / esp_timer interval` gives the slow clock directly (the `SLOWCLK` lines):

```
SLOWCLK p10000t tick_gap=13390 interval_us_milli=86980000 hz_milli=153943   (73.5 ms period + 13.4 ms work)
SLOWCLK p100t_a tick_gap=2244  interval_us_milli=14496652 hz_milli=154794
SLOWCLK p100t_b tick_gap=2245  interval_us_milli=14496652 hz_milli=154863
SLOWCLK p100t_c tick_gap=2246  interval_us_milli=14496652 hz_milli=154932
SLOWCLK p10t    tick_gap=2143  interval_us_milli=13971209 hz_milli=153386
SLOWCLK p1t     tick_gap=2135  interval_us_milli=13653681 hz_milli=156368
```

The four period-dominated phases agree at **154.9 kHz ± 0.4 kHz (±0.25 %)**; the work-limited phases
(`p10t`, `p1t`) read 153.4–156.4 kHz because their interval is set by the ULP's own run time, whose
tick sampling is coarser. Taking 154.9 kHz:

> **core clock = 122.64 cycles/tick × 154.9 kHz = 19.0 MHz**, uncertainty
> ±(1.5 × 0.20 % + 0.25 %) ≈ **±1.5 %, i.e. 19.0 MHz ± 0.3 MHz**.

Two independent checks that this is not an artefact: (a) a 4-cycle dependent `addi` at 19 MHz means
4.75 M dependent-op/s, consistent with a single-issue in-order core and with the 8.1-cycle RTC-RAM load
latency; (b) run 1's crude `span_wake / wake interval` estimate for a 137 935-cycle wake already
pointed at ~18 MHz.

**The cross-check against 136 kHz fails, and the doc figure is the wrong one.** The ESP32-S3 default
`RTC_SLOW_CLK` source is the internal RC oscillator with **150 kHz nominal** (`SOC_CLK_RC_SLOW_FREQ_APPROX`
= 150 000 for S3); 136 kHz is the "typical measured" number quoted for the *ESP32*. 154.9 kHz is
+3.3 % from 150 kHz nominal — inside that oscillator's spread — and **+14 % from 136 kHz**, far outside
the ~0.25 % measurement uncertainty. So:

* `cycles_per_tick = 122.6` is solid regardless: it is a pure `rdcycle`-versus-counter ratio and does
  not depend on the absolute slow clock at all;
* every *time* figure derived from "136 kHz" is 14 % wrong: **1 tick = 6.46 µs, not 7.35 µs**;
* the S3 `ULP_RISCV_CYCLES_PER_US 17.5` constant is **8 % below** the measured 19.0 MHz, so
  `ulp_riscv_delay_cycles` / `ULP_RISCV_CYCLES_PER_MS` run ~8 % short (IDF's own approximation,
  unrelated to this chip).

## 3. Verdict

**PASS** on both reproducibility criteria; **one documented disagreement** on the RTC_SLOW_CLK
cross-check, attributed to the doc figure, not to the measurement.

* **`cycles_per_tick = 122.6`** (K=1024: 122.541–122.780, 0.20 %; all 12 measurements 122.093–123.046,
  0.78 %). Pass criterion "reproducible across three runs within 5 %" is met with a factor of 6 to
  spare.
* **Implied core frequency 19.0 MHz ± 0.3 MHz (±1.5 %)** = 122.6 × 154.9 kHz. Pass criterion "implied
  frequency consistent with the instruction counts (no anomaly > 2×)" met: 4-cycle dependent ALU ops
  and 8.1-cycle RTC-RAM loads at 19 MHz are self-consistent, and the independent
  `span_wake / wake interval` route lands on the same number.
* **Pass criterion "RTC_SLOW_CLK cross-check agrees with 136 kHz" FAILS at 154.9 kHz.** The slow clock
  is the ~150 kHz RC oscillator (+3.3 % of nominal, +14 % of the 136 kHz figure). `cycles_per_tick` is
  unaffected; every tick→µs conversion must use 154.9 kHz.
* **`rdcycle` counts real cycles** (32-bit, reset at each wake, 81-cycle entry constant) — the
  "`rdcycle` does not count what we assume" failure mode is ruled out.
* **Instruction costs (settled in run 1, re-confirmed in run 2):** 4.000 cycles per dependent `addi`,
  8.1 per RTC-RAM `lw`, 8.6 per byte load.
* **D7 failure criterion triggered:** byte access 8.6 ≥ 4, so byte-wise `rd32` costs ~69 cycles per cell
  access versus 8.1 for one native `lw` (8.5×). **D7 is a required fix.**
* **§8's "connected mode 1–4 ticks" is dead as written.** A 1-tick wake has **122.6 cycles**, of which
  **81 are the wake entry itself** leaving **≈41 cycles ≈ 10 dependent ALU ops or 5 RTC RAM word
  loads** of real work — not one token, not one interpreted primitive. Four ticks give 490 − 81 = 409
  cycles ≈ 100 ALU ops. The brief's `cycles_per_tick < 200` failure criterion is met (122.6 < 200):
  **a 1-tick period cannot run a token interpreter; §8 must be restated in N ticks** (see §4.2), with
  the echo latency restated at 6.46 µs/tick.
* For scale, one *calibration* wake costs 259 k cycles ≈ 2115 ticks ≈ 13.7 ms — two orders of magnitude
  above a 1-tick budget, which is why §5's `period_ticks × 122.6 ÷ 2` must be applied to work that has
  been sized to the period.

## 4. Doc deltas

### 4.1 `docs/01-proposal.md` §5 — replace the "measured by calibration" placeholder

Current text:

> * **Budget** is `period_ticks × cycles_per_tick ÷ 2`, where `cycles_per_tick` is **measured** on the
>   chip by calibration, never assumed — the vendor docs do not state the core clock.

Proposed replacement (publishable now, with the tick factor left explicitly open):

> * **Budget** is `period_ticks × 122.6 ÷ 2`, where **`cycles_per_tick = 122.6`** and the
>   per-instruction costs are **measured on the chip** (P05, 12 independent measurements, 0.78 %
>   spread): a dependent ALU op is **4 cycles**, an RTC-RAM word load is **8.1 cycles**, a byte load
>   is **8.6 cycles**, and entering `main` costs **81 cycles** per wake — a third of a 1-tick budget.
>   The ULP core runs at **19.0 MHz ± 0.3 MHz**, and one tick is **6.46 µs** (measured slow clock
>   154.9 kHz; the 136 kHz figure in circulation is 14 % low).

### 4.2 `docs/01-proposal.md` §8 — 1–4 ticks is impossible, restate in N ticks

The brief's `cycles_per_tick < 200` trigger is met (122.6), so "Connected 1–4 ticks" must go.
Proposed replacement for the table's first row and its heading:

> | **Connected** | **32 ticks** (≈207 µs) | terminal attached; echo and `ok` feel immediate |
>
> Budget arithmetic that justifies 32: one wake carries `period_ticks × 122.6 − 81` cycles of work, and
> a byte-wise interpreter step is modelled at ≥ 8.6 cycles per access (P05), so a 1-tick period leaves
> **41 cycles ≈ 10 ALU ops** — less than a single token. Ticks are **6.46 µs** each, so 32 ticks is
> 207 µs, 8 ticks is 52 µs, and any "1–4 ticks (7–30 µs)" text is to be deleted. The final N is set by
> P06's cycles/token; until then quote the formula `N = (cycles_per_token + 81) ÷ 122.6`.

### 4.3 `docs/03-prototype-review.md` D7 — becomes **required**

Current: `### D7 (S) — 32-bit access is byte-at-a-time` … "the first thing to measure and probably
the first thing to fix".

Proposed:

> `### D7 (R) — 32-bit access is byte-at-a-time — REQUIRED`
> **Measured (P05): 8.6 cycles per byte access, 8 × 8.6 ≈ 69 cycles per `rd32` cell read, against
> 8.1 cycles for one native `lw` — an 8.5× penalty.** The failure criterion "cycles per byte-access
> ≥ 4 ⇒ D7 becomes required" is met. Byte-wise `rd32`/`wr32` must be replaced by native `lw`/`sw`
> for the `,`-allocated cells, `V_*`, and the `u32[]` stacks **before** any cycles/token figure is
> quoted; the careful path stays only for `@`/`!` on unaligned addresses.

### 4.4 `probe/EVIDENCE.md` — new entry (E-00x)

> ## E-00x — P05 ULP-RISC-V instruction costs (PARTIAL)
>
> ```
> cd probe/results/P05-clock && idf.py set-target esp32s3 && idf.py build && idf.py -p /dev/ttyACM0 flash
> stty -F /dev/ttyACM1 115200 raw -echo -crtscts; timeout 25 cat /dev/ttyACM1 > run1.log
> ```
>
> ```
> BLOCK addi span10=5601 span30=13601 delta=8000 milli_cycles_per_op=4000
> BLOCK lw   span10=9400 span30=25601 delta=16201 milli_cycles_per_op=8100
> BLOCK lb   span10=11400 span30=28601 delta=17201 milli_cycles_per_op=8600
> RAW   cyc_top=81 span_wake=137935 (constant across wakes)
> ```
>
> Method: 10-vs-30 instruction differential, 100 iterations, 3 independent runs.
> **4.000 cycles per dependent `addi`; 8.10 per RTC-RAM `lw`; 8.60 per `lb`; 81 cycles of reset→`main`
> overhead; `rdcycle` is a 32-bit counter reset at each wake.** Project: `probe/results/P05-clock/`.
>
> ## E-00y — P05 clock calibration: cycles per RTC tick and core frequency
>
> Same project, run 2 (`build2.log`, `flash2.log`, `run2.log`): latch `RTC_CNTL_TIME_UPDATE`
> (BIT(31) of `RTCCNTL+0xC`), poll it clear, then poll the counter forward by K ticks between two
> `rdcycle` reads.
>
> ```
> TICK p100t_a span64=7875 dt64=64 mcyc64=123046 span256=31482 dt256=256 mcyc256=122976 span1024=125727 dt1024=1024 mcyc1024=122780
> TICK p100t_b ... mcyc1024=122541   TICK p100t_c ... mcyc1024=122720
> SLOWCLK p100t_b tick_gap=2245 interval_us_milli=14496652 hz_milli=154863
> ```
>
> **`cycles_per_tick = 122.6`** (K=1024: 122.541–122.780, 0.20 %; 12 measurements 122.093–123.046,
> 0.78 %). Measured **RTC_SLOW_CLK = 154.9 kHz ± 0.5 kHz** → **ULP core clock 19.0 MHz ± 0.3 MHz
> (±1.5 %)**; 1 tick = **6.46 µs**. The RTC_SLOW_CLK cross-check against the often-quoted 136 kHz
> fails by 14 % — the S3 default is the 150 kHz RC oscillator, so the 136 kHz figure is wrong, not the
> measurement. A 1-tick wake gives 122.6 cycles, 81 of them wake entry, i.e. **~10 ALU ops of work**:
> a 1-tick period cannot run a token interpreter.

### 4.5 New delta — the RTC_SLOW_CLK / clock-source figures (docs 00-background.md, 01-proposal.md §5)

Anywhere the documents state the ESP32-S3 `RTC_SLOW_CLK` as 136 kHz, add the measured value:

> Measured on this board (P05): **RTC_SLOW_CLK = 154.9 kHz ± 0.5 kHz** (150 kHz RC oscillator,
> +3.3 % of nominal, +14 % of the commonly quoted 136 kHz). One tick is therefore **6.46 µs**, not
> 7.35 µs. The ULP-RISC-V core clock measures **19.0 MHz ± 0.3 MHz** — the IDF constant
> `ULP_RISCV_CYCLES_PER_US = 17.5` is 8 % low, so `ulp_riscv_delay_cycles()` under-delays by ~8 %.

## 5. Follow-ups

1. **P06 (now unblocked):** cycles/token with `rdcycle`, then pick N for §8 with
   `N = (cycles_per_token + 81) ÷ 122.6`. Resources available: 122.6 cycles/tick, 81 cycles of entry,
   4.0 cycles per ALU op, 8.1 per RTC-RAM `lw`, 8.6 per byte access.
2. **D7 is required, not optional** (8.6 ≥ 4 cycles per byte access): replace byte-wise `rd32`/`wr32`
   with native `lw`/`sw` for `,`-cells, `V_*` and the `u32[]` stacks before quoting cycles/token.
3. **Any timing figure derived from 136 kHz must be recomputed at 154.9 kHz** (14 % error), and the
   IDF `ULP_RISCV_CYCLES_PER_US` constant must not be trusted for delays (8 % short).
4. Still owed from the brief: the `CONFIG_ULP_COPROC_RESERVE_MEM=8176` repeat (both runs used the
   default 4096). Low risk — the measurements read no memory-map-dependent quantity — but not done.
5. Cosmetic, in the probe only: the inverted `top_min`/`top_max` comparison in `main.S` is still
   present (harmless, `cyc_top` is constant), and the ~±2 % loop-alignment sensitivity of the `lw`
   differential would be removed by aligning the two loops to the same 16-byte boundary.

## What is flashed on the board now

The ESP32-S3 at `/dev/ttyACM0` is running **this probe's run-2 image**
(`probe/results/P05-clock/build/p05_clock.bin`, ESP-IDF v5.4, ULP-RISC-V enabled,
`CONFIG_ULP_COPROC_RESERVE_MEM` = default (4096), built from `main/p05_clock_main.c` +
`main/ulp/main.S` with the `TIME_UPDATE` latch and the real-`esp_rom_delay_us` windows).

`app_main` ends with `ulp_riscv_timer_stop()`; the ULP kernel always returns from `main` into
`ulp_riscv_halt()`, so **the ULP is halted, not spinning**, and the HP core sits in the idle task.
The board was already running a P05 image before this run (run 1); the pre-P05 firmware was
overwritten earlier with approval and no backup of it exists in this repo.

The earlier "source vs flashed binary" caveat no longer applies: `RESULT.md` now describes exactly the
image that is on the board, and run 2's numbers come from that image.
