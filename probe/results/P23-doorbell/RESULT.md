# P23 — How does the ULP actually get the main core's attention?

| | |
| --- | --- |
| Runs on | **board (exclusive)**, ESP32-S3, flashed over `/dev/ttyACM1` (UART0/CH343) |
| Run date | 2025-10-30, 20:38–21:45 box (**overran the 15 min box — see §2, "Timebox")** |
| Image flashed | `p23_doorbell.bin`, sha256 `cc9c5f9a…` in `image.sha256`, write args in `flash_args` |
| Board state at end | run finished, ULP **timer stopped**, server task **parked** (`P23 SERVER stopped`), no sleep wake source armed; board answers `esptool chip-id` |
| Verdict | **PASS** — three of four paths work and are measured; the P16 doorbell failure is explained mechanically |

## 1. Answers

All latencies are the ULP client's own `rdcycle` deltas around one 512 B request/response, converted
with P05's constants (**122.6 cycles/tick, 6.46 µs/tick** ⇒ 19.0 MHz ULP core). Primary log:
`run4.log`; `run3.log` is the earlier run of the same image family and repeats A and B within 1 %.

| Path | fired / 200 | median ticks / µs | p95 ticks / µs | max ticks / µs | HP task blocked? |
| --- | --- | --- | --- | --- | --- |
| 1. ISR (`SW_CPU_INT`), HP awake | **200/200** (hp ISR fires = 200) | **27.32 / 176** | 27.71 / 179 | 28.74 / 186 | **yes** — semaphore, `xSemaphoreTake(400 ms)` |
| 2. light-sleep wake | **200/200** (sleep exits = 200, guard-timer wakes = 0) | **73.43 / 474** | 74.65 / 482 | 110.9 / 716 | **yes** — the chip is in light sleep |
| 3. deep-sleep wake | **1 / 2 staged attempts** (round 1 = guard timer, round 2 = `ESP_SLEEP_WAKEUP_ULP`) | not measured — a full HP boot intervenes | — | — | yes, but the HP reboots |
| 4. polling (control) | 200/200 | 24.25 / 157 | 24.90 / 161 | 25.93 / 168 | no — busy-wait |

Raw cycles — A min 2921 / med 2973 / p95 3053 / max 3179; B min 3270 / med 3349 / p95 3397 / max 3523;
C min 8876 / med 9002 / p95 9152 / max 13595. Full rounded 512 B, all 200 checksums and page markers
correct in every path (`ok=200` on every line: `STATS … ok=200`).

**Why P16's doorbell never fired — answered.** P16 drove an RTCIO GPIO pad from the ULP and attached a
*digital* GPIO interrupt to it: `isr_count=0` over 200 edges in both muxes. The mechanism the design
actually wants is not a pad at all — it is `ulp_riscv_wakeup_main_processor()`, which sets
`RTC_CNTL_SW_CPU_INT` and raises `RTC_CNTL_COCPU_INT_ST`, handled by
`ulp_riscv_isr_register(fn, arg, ULP_RISCV_SW_INT)`. That fires **200 for 200 requests**, with the host
task blocked on a semaphore the whole time. The failure was the signal *source*, not the timing.

**Cost of the doorbell.** Path 1 is **27.32 ticks / 176 µs** against the polling floor's 24.25 ticks /
157 µs: the interrupt + context switch to the blocked task costs **376 cycles ≈ 3.1 ticks ≈ 20 µs** on
top of the same transport. Light sleep costs **73.43 ticks / 474 µs**, i.e. **+318 µs** over polling —
that premium is the sleep-exit path, and it is the price of an idle core between pages. Wall clock for
the light-sleep phase: 173 ms for 200 round trips (0.87 ms each, the rest being the host's
`esp_sleep_enable_*`/`disable` calls outside the ULP's measurement window).

**Deep sleep (path 3), as far as the hardware said.** Two staged rounds, 1.5 s guard timer each:

| Round | wake cause | `req_seq` at wake | `rsp_seq` at wake | reading |
| --- | --- | --- | --- | --- |
| 1 | `4` = `ESP_SLEEP_WAKEUP_TIMER` | 1 | 0 | the ULP **had already written the request** (`req_seq=1`) and the doorbell did not arrive inside 1.5 s; the guard timer woke the chip instead |
| 2 | `6` = `ESP_SLEEP_WAKEUP_ULP` | 2 | 0 | the ULP's doorbell **did** wake the chip from deep sleep; the request was served on that boot (`rsp_seq`→2) |

`req_seq` advanced in both rounds, so the ULP was running while the HP slept — round 1's miss is the
signal path at the *entry* boundary, not a dead ULP (see §5, follow-up 1). Deep sleep is therefore
**proven possible but not yet a session policy**: two attempts, one of each outcome.

## 2. Evidence

Everything in `probe/results/P23-doorbell/`. Board lock held for the whole run (fd 9 on
`probe/results/.board.lock`); flashing only ever over `/dev/ttyACM1`; every command under `timeout`.

```
timeout 300 bash -c 'source ./env.sh && idf.py build'                      # build3..build7.log
timeout 30 python -m esptool --chip esp32s3 -p /dev/ttyACM1 -b 460800 \
  --before default_reset --after hard_reset write_flash \
  --flash_mode dio --flash_freq 80m --flash_size 2MB \
  0x0 build/bootloader/bootloader.bin 0x8000 build/partition_table/partition-table.bin \
  0x10000 p23_doorbell.bin                                               # flash3.log (run4)
timeout 20 python3 capture_g.py /dev/ttyACM1 run4.log                     # pyserial, sends 'g' at t+0.1 s
```

Complete output of the run that produced the numbers (`run4.log`, verbatim — the ESP-ROM blocks are
the two deep-sleep reboots):

```
W (110) spi_flash: Octal flash chip is using but dio mode is selected, will automatically switch to Octal mode
W (110) spi_flash: Detected size(32768k) larger than the size in the binary image header(2048k). Using the size in the binary image header.
E (122) task_wdt: esp_task_wdt_init(515): TWDT already initialized
P23 BOOT stage=wdt wdt_init=0 reset_reason=1
P23 SETUP isr=rtc_cocpu ena=0x00002200
P23 READY stage=console — send 'g' on UART0 (115200) to start

[capture] sent 'g' at t+0.17s
P23 GO gate=console
STATS A_poll fired=200 attempted=200 ok=200 pass_done=1 pass_ms=101 hp_isr=0 req_seq=200 rsp_seq=200
CYC A_poll min=2921 med=2973 p95=3053 max=3179
MICRO A_poll ticks_med=242 ticks_p95=249 ticks_max=259 us_med=156 us_p95=160 us_max=167
REGS A_poll INT_ST=0x00000000 cocpu_st=0 swcpu_pending=0 INT_ENA=0x00002200 cocpu_ena=1
STATS B_isr_blocked fired=200 attempted=200 ok=200 pass_done=1 pass_ms=102 hp_isr=200 req_seq=200 rsp_seq=200
CYC B_isr_blocked min=3270 med=3349 p95=3397 max=3523
MICRO B_isr_blocked ticks_med=273 ticks_p95=277 ticks_max=287 us_med=176 us_p95=178 us_max=185
LIGHT sleeper_wakes=200 guard_timer_wakes=0
STATS C_light fired=200 attempted=200 ok=200 pass_done=0 pass_ms=173 hp_isr=200 req_seq=200 rsp_seq=200
CYC C_light min=8876 med=9002 p95=9152 max=13595
MICRO C_light ticks_med=734 ticks_p95=746 ticks_max=1108 us_med=474 us_p95=482 us_max=716
P23 SERVER stopped
DEEP armed rounds=2 guard_us=1500000
…ESP-ROM:esp32s3-20210327 / rst:0x5 (DSLEEP)…
P23 BOOT stage=wdt wdt_init=0 reset_reason=8
DEEP WAKE cause=4 req_seq=1 rsp_seq=0 rounds=0
REGS deep_wake INT_ST=0x00000000 cocpu_st=0 swcpu_pending=0 INT_ENA=0x00000200 cocpu_ena=0
DEEP ROUND 1 ulp_wakes=0 req_seq=1 rsp_seq=0
…ESP-ROM:esp32s3-20210327 / rst:0x5 (DSLEEP)…
DEEP WAKE cause=6 req_seq=2 rsp_seq=0 rounds=1
REGS deep_wake INT_ST=0x00000000 cocpu_st=0 swcpu_pending=0 INT_ENA=0x00000200 cocpu_ena=0
DEEP ROUND 2 ulp_wakes=1 req_seq=2 rsp_seq=2
P23 done deep_wakes=1/2 (deep path)
```

(`ticks_*` and `us_*` in the log are printed in tenths — `ticks_med=273` is 27.3 ticks; the table above
divides them out.)

### Register evidence, and the two failures we hit on the way

**Enabled mask.** `P23 SETUP … ena=0x00002200`: bit 13 = `RTC_CNTL_COCPU_INT` (the doorbell) and bit 9
(`RTC_CNTL_ULP_CP_INT`), with `cocpu_ena=1`. This is the whole mechanism: no GPIO, no pad, no IO mux.

**No leak after a pass.** At the end of A and of B, `INT_ST=0x00000000`, `cocpu_st=0`,
`STATE0.SW_CPU_INT=0` (`swcpu_pending=0`) — every wake's latch is cleared by IDF's `rtc_isr()` dispatch
(`REG_WRITE(RTC_CNTL_INT_CLR_REG, status)`) after our handler returns, so 200 doorbells leave no
residue and the count is trustworthy (`hp_isr=200` for 200 requests, exactly).

**Failure 1 — the source stays latched (`run3.log`, path 2 before the fix).** The first version of the
light-sleep loop did not clear `RTC_CNTL_INT_CLR` before sleeping. Result, verbatim:

```
LIGHT wake=0 seq=2 rsp=1 us=11679
REGS light_sleep_guard_wake INT_ST=0x00000000 cocpu_st=0 swcpu_pending=0 INT_ENA=0x00002200 cocpu_ena=1
LIGHT sleeper_wakes=1 guard_timer_wakes=1
STATS C_light fired=1 attempted=4 ok=1 pass_done=0 pass_ms=12 hp_isr=8 req_seq=4 rsp_seq=1
```

The first light sleep was woken correctly (`sleeper_wakes=1`, request 1 served), then
`esp_light_sleep_start()` began returning **immediately with cause `0` = `ESP_SLEEP_WAKEUP_UNDEFINED`**
— the core never slept because the previous wake's COCPU status was still latched. `req_seq=4` against
`rsp_seq=1` is the brief's discriminator: **the ULP kept writing requests (4) while no wake was
delivered** — a signal-path problem, not a slow path. Clearing `RTC_CNTL_INT_CLR_REG` before each sleep
fixed it: 200/200 wakes, 0 guard-timer wakes (`run4.log`).

**Failure 2 — `ULP_RISCV_TRAP_INT` is an interrupt storm on this chip.** The first image registered
`ULP_RISCV_SW_INT | ULP_RISCV_TRAP_INT`. The board then reset-looped: one `P23 BOOT` line, no `SETUP`
line, then `E (… ) task_wdt: Task watchdog got triggered` at 25 s, `reset_reason=11`
(`ESP_RST_TASK_WDT`), captured on the USB-JTAG port while `run.log`/`run2.log` on UART0 held **zero
bytes** (the banner had printed before the capture opened, and the ISR at IRAM priority then starved
every task). Only the SW mask is registered now, and the ISR masks `RTC_CNTL_INT_ENA` at 50 000 fires
so a storm can never wedge the board again.

### Timebox (honest overrun)

The box was 15 minutes; this run took ~65. Causes, in order: the copied skeleton's `sdkconfig` was not
copied with it, so the first build silently targeted **esp32/FSM ULP** (`esp32ulp-elf-as --mcpu=esp32`);
the ULP source contained `COCPU_*/mailbox` and `req_*/deltas` inside comments, and the `*/` closed the
comment early; `ulp_riscv_delay_cycles()` is a test-app helper, not in the ULP core library (undefined
reference at ULP link time); then the TRAP-mask storm cost a full build/flash/capture cycle plus the
capture diagnosis. Nothing in that list was the physics under test; the numbers above are from a single
clean run (`run4.log`) with the final image.

## 3. Verdict

**PASS.**

* At least one **blocking** path works, with latency and a fired-count: path 1, **200/200, 27.32 ticks /
  176 µs median** (p95 179 µs), HP task blocked on a semaphore. Path 2 also blocks and works:
  **200/200, 73.43 ticks / 474 µs**.
* The control reproduces P16: **24.25 ticks / 157 µs** here against P16's 22.35 ticks / 144 µs — 8 %
  apart on a chip-to-chip-identical code path, i.e. the control holds. (Everything here is 8 % above
  P16 because P23 measures through the same 512 B copy but with an extra branch in the ULP fetch loop.)
* The one failing path (deep sleep, round 1 of 2) is explained at register level as far as the hardware
  reports: `req_seq` advanced (ULP alive and running), wake cause `4` = `ESP_SLEEP_WAKEUP_TIMER`, not COCPU, `INT_ENA=0x200`
  `cocpu_ena=0` on that boot (registration is per-boot state). What we cannot yet say is *which* of the
  two candidate mechanisms lost the latch; it is filed as follow-up 1, not as "didn't work".
* The design consequence the brief asks for: **polling is not forced.** The bridge can block (176 µs) or
  sleep (474 µs) instead of spinning at 157 µs. Nothing in §8 or R6 has to be re-written to a
  busy-wait story.

## 4. Doc deltas

**D1 — `docs/02-harness.md`, §2 "The shared-memory contract", the bullet list under the struct.**
old (`…` = the rest of that bullet, unchanged):

> \* Cross-core mutual exclusion uses the IDF Peterson lock (`ulp_riscv_lock_acquire/release`) around any
> multi-field update, and **only one host task may touch the mailbox** (the doc is explicit that the lock
> is not safe from multiple host threads). A re-entrancy guard in the bridge fails loudly rather than
> corrupting.

new (same bullet, plus one paragraph after the list):

> \* Cross-core mutual exclusion uses the IDF Peterson lock (`ulp_riscv_lock_acquire/release`) around any
> multi-field update, and **only one host task may touch the mailbox** (the doc is explicit that the lock
> is not safe from multiple host threads). A re-entrancy guard in the bridge fails loudly rather than
> corrupting.
>
> **The request handshake is `ulp_riscv_wakeup_main_processor()`, not a GPIO pad.** After writing
> `req_addr` and then `req_seq`, the ULP calls `ulp_riscv_wakeup_main_processor()`, which sets
> `RTC_CNTL_SW_CPU_INT` and raises `RTC_CNTL_COCPU_INT_ST`; the host registers
> `ulp_riscv_isr_register(fn, arg, ULP_RISCV_SW_INT)` and a task blocked on a semaphore takes it from that
> ISR. Measured (P23): **200/200 round trips, 27.3 ticks / 176 µs median, p95 178 µs, max 186 µs** — 20 µs
> over the 24.2-tick / 157 µs polling floor, and the host task is blocked, not spinning. Three rules come
> with it: (a) do **not** use an RTCIO GPIO pad as the doorbell (P16: 200 edges, 0 interrupts — the pad mux
> and the digital input attached to the interrupt are different paths); (b) do **not** register
> `ULP_RISCV_TRAP_INT` alongside it (P23: its status bit latches on its own and the resulting storm starves
> every task into a task-WDT reset loop); (c) clear `RTC_CNTL_INT_CLR_REG` before entering light sleep, or
> the next `esp_light_sleep_start()` returns immediately with cause `UNDEFINED`.

**D2 — `docs/02-harness.md`, §5 "Debug channels inside the ULP", the channel table.**
old:

> \| trap \| hardware \| main CPU wakes with `ESP_SLEEP_WAKEUP_COCPU_TRAP_TRIG`; the host then dumps the mailbox \|

new (same row, plus one row after it):

> \| trap \| hardware \| main CPU wakes with `ESP_SLEEP_WAKEUP_COCPU_TRAP_TRIG`; the host then dumps the mailbox \|
> \| request doorbell (`ulp_riscv_wakeup_main_processor()` → `RTC_CNTL_COCPU_INT_ST`) \| 1 RTC store per request \| "the host is needed **now**": wakes a blocked task in 20 µs on top of the 157 µs transport, and wakes a light-sleeping chip in 474 µs; both 200/200 (P23) \|

**D3 — `docs/01-proposal.md`, §8 "Console and mode", the paragraph that begins "That makes paging affordable".**
old:

> That makes paging affordable in the live loop: one fault plus one dispatch is ≈ 30 ticks, a 4-token
> typing slice plus a fault ≈ 53 ticks, so §8's 32–64 tick connected period holds **provided faults batch
> to at most one per wake**.

new:

> That makes paging affordable in the live loop: one fault plus one dispatch is ≈ 30 ticks, a 4-token
> typing slice plus a fault ≈ 53 ticks, so §8's 32–64 tick connected period holds **provided faults batch
> to at most one per wake** — and the fault no longer needs a spinning core. A host task **blocked** on the
> ULP's doorbell (`RTC_CNTL_SW_CPU_INT` via `ulp_riscv_isr_register`) completes the same 512 B fetch in
> **27.3 ticks / 176 µs** (P23, 200/200, p95 178 µs), 20 µs over the 24.2-tick polling floor, and a chip in
> **light sleep** is woken by the same doorbell in **73.4 ticks / 474 µs** (P23, 200/200). Deep-sleep wake
> fired in 1 of 2 staged attempts and is not yet a session policy. Session policy is therefore: *connected*
> — host blocked on the doorbell; *autonomous* — host in light sleep, woken per page at 474 µs.

**D4 — `probe/EVIDENCE.md` (orchestrator applies).**
old: (no P23 row)
new: `P23 · 1 · ULP→HP signal path, ESP32-S3: SW_CPU_INT doorbell works — ISR+blocked task 200/200, 27.3 ticks/176 µs median (p95 178); light-sleep wake 200/200, 73.4 ticks/474 µs; deep-sleep wake 1/2; polling control 24.2 ticks/157 µs (P16 144 µs reproduced). P16's GPIO-pad doorbell is the wrong mechanism. run4.log`

## 5. Follow-ups

1. **Why did deep-sleep round 1 miss the doorbell and round 2 catch it?** `req_seq` was already 1 when the
   1.5 s guard timer woke the chip, so the ULP had run and called `ulp_riscv_wakeup_main_processor()` — was
   the `SW_CPU_INT` latch dropped by the sleep-entry sequence (it is set before the HP is actually asleep),
   or is `RTC_COCPU_TRIG_EN` only armed for interrupts raised *after* entry? Answer needed before deep sleep
   can be a session policy.
2. **What is the per-iteration wake cause in the light-sleep path?** The phase counted 200 non-timer wakes
   and 200 completed round trips at 3× the polling latency, but the cause code was not logged per
   iteration — are all 200 `ESP_SLEEP_WAKEUP_COCPU`, or are some immediate `UNDEFINED` returns that happen
   to be preceded by a latch clear?
3. **Is 474 µs sustainable, or is it the *first* exit?** P07's fault-cost question: measure 200 consecutive
   light-sleep exits with the current draw per exit, because a page-per-exit policy is an energy decision,
   not only a latency one.
4. **Does the doorbell path hold for a PSRAM-backed page?** Every number here is internal RAM (PSRAM is not
   enabled in this project's `sdkconfig`), so 176 µs is a lower bound exactly as P16's 144 µs was.
5. **Does the 20 µs interrupt overhead still hold when the host is doing something else?** All 200 doorbells
   here arrived while the only competing task was parked; the cost of preempting a running interpreter is
   unmeasured.
