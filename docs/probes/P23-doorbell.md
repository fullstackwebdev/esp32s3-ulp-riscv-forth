# P23 — How does the ULP actually get the main core's attention?

| | |
| --- | --- |
| Runs on | **board (exclusive)** — flashes; use `/dev/ttyACM1` |
| Time box | **15 min**, one run, hard cap |
| Depends on | P16 (the doorbell failed there) |
| Blocks | the byte server (R6), and with it paging (R5) |
| Serves | R5, R6 |

## Question

P16 measured configuration A (main core polling) at 144 µs and could not measure configuration B at all:
the doorbell never fired — `isr_count = 0` across 200 attempts, with the pad tried in both the GPIO mux
and the RTC mux. So the one mechanism the whole design assumes — *the ULP wakes the main core* — is
currently unproven.

Which of these actually works, and with what latency?

1. `ulp_riscv_wakeup_main_processor()` (`RTC_CNTL_SW_CPU_INT`) waking a **blocked FreeRTOS task** via
   `ulp_riscv_isr_register()` on `RTC_CNTL_COCPU_INT_ST`.
2. The same call waking the chip from **light sleep**.
3. The same call waking the chip from **deep sleep** (the case the docs promise for sensors).
4. Polling `req_seq` from a normal task — the fallback we already know works (144 µs), included as the
   control.

## Why it matters

Everything that lets the big cores be *idle* instead of *spinning* depends on this. If the only working
path is polling, then the "main cores do communication and memory only" requirement (R6) is still met but
at the cost of a busy-waiting core — a different power story, and a different bridge design.

## Given — do not re-derive

* P16: A = 144 µs / 2 740 cycles per 512 B fetch; doorbell `isr_count = 0` (2 mux variants); the four
  failure modes; two-in-flight corrupts.
* IDF provides `ulp_riscv_isr_register(fn, arg, mask)` with `RTC_CNTL_COCPU_INT_ST_M` and
  `RTC_CNTL_COCPU_TRAP_INT_ST_M`, and `ulp_riscv_wakeup_main_processor()` sets `RTC_CNTL_SW_CPU_INT`.
* P06: never write `COCPU_*` from the HP while the ULP may be mid-wake — that wedged this board.
* Recovery: `esptool -p /dev/ttyACM1 chip-id` resets via RTS. Flash over UART0, never the native USB.

## Method

1. Board lock; watchdog first; banner; stage behind a console `g`.
2. For each of the four paths, measure **200 round trips**, reporting `rdcycle` deltas in ticks and µs:
   median / p95 / max, plus a count of how many fired at all.
3. For each path that fails, record **why as far as the hardware will say**: the ISR counter, the value of
   `RTC_CNTL_INT_ST_REG` and `RTC_CNTL_INT_ENA_REG` at the moment of timeout, and whether
   `COCPU_INT_ST` was ever set.
4. Prove the mechanism is not merely slow: after the timeout, read whether the ULP's `req_seq` advanced. If
   the ULP wrote a request and no interrupt arrived, the signal path is broken, not the timing.
5. Report the working path's latency **and** its cost: does the HP task block (good) or spin (fallback)?

## Record

| Path | fired / 200 | median ticks / µs | p95 | max | HP task blocked? |
| --- | --- | --- | --- | --- | --- |
| 1. ISR, awake | | | | | |
| 2. light-sleep wake | | | | | |
| 3. deep-sleep wake | | | | | |
| 4. polling (control) | 200/200 | 22.35 / 144 | 22.84 | 23.41 | no |

## Pass criteria

* at least one **blocking** path (1–3) works, with latency and a fired-count;
* any failing path is explained at register level, not left as "didn't work";
* the control (4) reproduces P16's 144 µs.

## Failure criteria — and what each changes

* **Only polling works** ⇒ the bridge must poll, and `02-harness.md` and R6 must say so: the main core
  spins while the ULP needs memory. That is a power decision the operator must see, not a footnote.
* **ISR fires but the task does not wake** ⇒ the registration is on the wrong mask or the ISR is not
  chained from the RTC ISR; report the exact registers and fix the registration, not the design.
* **Deep sleep works but light sleep does not** ⇒ §8's session policy changes: the bridge stays awake and
  the ULP pages only while the HP is up.
* **Nothing works and `req_seq` never advanced** ⇒ the ULP never ran; that is a different bug (image,
  timer, `DONT` bit) and must be reported as such.

## Doc deltas to hand back

* `docs/02-harness.md` §2 (mailbox handshake) and §5 (debug channels) — the working path and its latency.
* `docs/01-proposal.md` §8 — session policy if only polling works.

## Do not

* Do not leave the ULP armed, the timer stopped, or a busy task running; restore and say what is flashed.
* Do not touch `/dev/ttyACM0` for flashing.
