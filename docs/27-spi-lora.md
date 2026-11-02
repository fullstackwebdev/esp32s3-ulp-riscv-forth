# 27 — External SPI memory and LoRa on the ULP-RISC-V: research notes

**Status: notes, not findings.** Nothing in this file was measured on our boards. It is the record of a research
conversation (2026-11-01, at the point the ESP32-S3 was swapped for the LoRa board) and is kept so the reasoning and the
open questions survive. Every number here is either the datasheet-recalled order of magnitude or a forum-reported figure —
both are labelled where they appear. Before any of this becomes a design decision it has to be measured the same way
F-131…F-140 were measured: on the chip, with the probe, counter or scope that can be wrong.

Local context that *is* measured, and that constrains everything below: our ULP-RISC-V image already sits at
**7 891 of 7 892 B** of RTC slow memory (`ULP_POOL_BUDGET`, `probe/repl/main/repl_main.c`, checked by
`probe/repl/flash_safe.sh`). There is **1 B free**. Any ULP-side driver has to buy its bytes from the interpreter.

---

## 1. The question

> If I buy SPI RAM that is ultra low power, can I get this thing to stay on for months, using only the ULP, and have more
> RAM?

Short answer: **feasible, with real limits**, and the limits are not about the memory chip.

## 2. The limits, in order of how much they hurt

1. **The ULP cannot see external RAM.** It executes from, and addresses, only the 8 KB RTC slow memory. Extra memory can
   only ever be *data* — never a place to run code.
2. **The SPI and PSRAM peripherals are powered off in deep sleep.** The ULP would have to **bit-bang SPI** on RTC GPIO
   pins — clock, data in, data out, chip select.
3. **Every byte costs ULP cycles.** At 17.5 MHz with several cycles per GPIO toggle, the effective SPI clock is on the
   order of a few hundred kHz (see §4 for the forum numbers). Fine for logging sensor readings, slow for anything heavy.
4. **Shared pins must be handed over explicitly.** The pins are RTC GPIO while the ULP owns them and normal GPIO after the
   main CPU wakes; that reconfiguration has to be done, not assumed.

## 3. Which memory (trade-offs as stated, not recommendations)

| kind | fit | notes |
|---|---|---|
| chip PSRAM / pSRAM | **poor** | not designed for microamp standby; our module's PSRAM is powered down with the digital domain |
| small SPI SRAM (23LC-type, 32–128 KB) | simple and fast | standby typically a few µA; **loses data if power is cut** |
| SPI FRAM / MRAM (Infineon, Fujitsu, Everspin) | **best fit for months** | non-volatile, very low idle current, huge endurance; can be powered off between uses and lose nothing; smaller sizes, higher price |

## 4. FRAM/MRAM speed: the ULP is the bottleneck, not the memory

**ULP side (forum-reported estimates, not measurements):** the ULP-RISC-V runs at 17.5 MHz but most instructions take
several cycles — roughly 3–5 MIPS. Reported bit-banged SPI results: **235 kHz** with a first attempt, **350 kHz** after
switching to direct register writes, an estimate of ~417 kHz from ~6 instructions per bit, and a **1.1 MHz** figure that
was clock-pin toggling only, no data shifting. Practical expectation: **~250–400 kHz SPI clock ≈ 30–50 KB/s** before
command/address overhead.

**Memory side (datasheet-recalled, check before buying):** SPI FRAM (Infineon/Cypress FM25V, Fujitsu MB85RS) **20–40+ MHz**;
SPI MRAM (Everspin MR25H) **~40–50 MHz**; I²C FRAM (FM24) **~1 MHz**. So the memory is ~100× faster than the ULP can drive
it: **buying a faster part gains nothing.** Choose on standby current, capacity, voltage range, price. FRAM/MRAM reportedly
have no minimum clock — verify per datasheet, it matters for a slow ULP bus.

**Ways to go faster, in order of payoff:**
* **Burst transfers** — hold CS low and clock many sequential bytes after one opcode+address. Overhead is paid once.
* **Unroll the bit loop** in assembly or tight C: costs code space we do not have (§0), removes loop-counter instructions.
* **Direct single-register writes** instead of read-modify-write helpers — that is exactly what took the forum example from
  235 → 350 kHz.
* **The RTC I²C controller** does I²C master work in the RTC domain, so the ULP spends no instructions per bit. Catch: the
  pins are fixed (SDA on GPIO1 or 3, SCL on GPIO0 or 2) and its maximum clock and driver overhead are **unverified** —
  test before designing around it.
* **Do not chase speed you do not need.** For months on a battery the metric is **energy per byte**, not throughput. A few
  bytes per minute at 100 kHz is fine.

## 5. Months on a battery: the actual budget

* Deep sleep with RTC memory retained: **single to low-double-digit µA** (datasheet-recalled §; verify).
* The ULP adds to that, and adds more the more often it wakes and the longer it runs → **short bursts on the ULP timer**,
  not continuous running.
* External memory standby adds **directly** — pick a part whose standby is *well under* the chip's floor.
* Pins connected to the memory must hold state during sleep with **CS inactive**: plan RTC GPIO hold explicitly.
* A coin cell for months is plausible **only at a very low duty cycle**; a pair of AAs or a small LiPo gives real room.

## 6. The architecture that fits

1. ULP wakes on a timer, reads sensors, **appends records to the external memory over bit-banged SPI**.
2. Now and then the main CPU wakes, reads the whole buffer with **hardware SPI + DMA**, and sends it over Wi-Fi/BLE.
3. The main CPU **reconfigures the shared pins from RTC to normal GPIO** after waking — explicitly, as a step.

## 7. If the goal is large retained RAM + months + Forth

Consider a chip built for it instead of fighting the S3: **MSP430FR** (FRAM, long Forth tradition — current ports
unverified), **STM32L-series**, or **Nordic** parts with retention RAM. They run from internal RAM with no bit-banging, at
the cost of the S3's Wi-Fi/BLE.

## 8. Forth-specific consequence

A tiny kernel could live in the 8 KB with the dictionary and bytecode in external memory — but **fetching each instruction
over bit-banged SPI is slow**: "thousands of words per second at best" (estimated). Workable for low-duty-cycle logging,
a poor fit for fast loops. Our current design already assumes the opposite: the interpreter lives entirely in RTC memory and
the store is reached through the block server, which is a *bulk* channel, not an instruction fetch.

## 9. LoRa (SX126x) on the ULP

**No public example of an SX126x driver running on the ULP-RISC-V was found** (searches surfaced main-CPU drivers only;
absence of evidence, not proof).

Candidates worth porting from:
* **TravisBubb/sx126x-driver** — best structural fit: radio logic separated from a thin HAL, with an ESP32 example HAL.
  Port = a new ULP HAL (bit-banged SPI, GPIO, timing) + compiling the core with the ULP toolchain. Code size and IDF
  coupling unread/unmeasured.
* **Semtech LoRaMac-node / SWSD003** — the origin of most others; `lupyuen/lora-sx1262` shows how little the core needs
  from the OS. Uses hardware-specific waits (e.g. BUSY pin) that must be reimplemented. Probably too big for 8 KB in full.
* **Arduino C++ libraries** (dj0abr, beegee-tokyo SX126x-Arduino) — **poor** starting points: C++ on the Arduino + ESP32 SPI
  stack, neither of which exists on the ULP.

Two ideas imported from beegee-tokyo's deep-sleep example that apply regardless: the radio keeps its configuration while
the CPU sleeps (no reset/reconfigure on IRQ wake), and **DIO1, RESET and NSS are held at fixed levels during deep sleep
via RTC GPIO**. It also uses the chip's **RX duty-cycle mode** (radio mostly asleep, wakes briefly to catch packets).

**Porting gotcha:** ULP code cannot call into the main application — no ESP-IDF LoRa component can be linked. The whole
driver must be compiled **into the ULP binary**.

**TX-only command set** (from knowledge of the SX126x command set, not from the repos): set standby, set packet type, set
frequency, set PA config + TX params, set modulation + packet params, set buffer base address, write buffer, set IRQ params,
set TX, get/clear IRQ status, set sleep — plus TCXO and RF-switch control on many modules. Roughly a dozen commands: small
enough that a stripped port is *plausible* in 8 KB. Not measured.

## 10. What must be verified before this becomes a design

| claim | how to settle it |
|---|---|
| deep-sleep floor µA with RTC retained | datasheet + our own measurement with the LoRa board |
| ULP bit-banged SPI ceiling (~250–400 kHz) | our own loop, clocked out with a counter — we have the tooling habit already (F-131…F-140) |
| FRAM/MRAM max clock is irrelevant at ULP rates | accepted by arithmetic; confirm part datasheets for ≥ our ceiling |
| FRAM/MRAM no-minimum-clock | **per-datasheet**, do not assume |
| RTC I²C controller max clock and overhead | measure; fixed pins GPIO0–3 must not collide with the LoRa wiring |
| SX126x driver fits in the ULP pool | `riscv32-esp-elf-size` against **7 892 B**, with 1 B free today |
| record size vs. months of battery | energy per byte × records/day × standby; needs a number, not a feeling |

## 11. Where the work would start

A minimal ULP-RISC-V HAL (bit-banged SPI, BUSY wait, delay) plus a TX-only command sequence, tested first against a
simulated SX126x on the host and then size-built for the RISC-V target. Not started. The first real question is not the
driver but the **byte budget**: the ULP image has 1 B of headroom, so a LoRa path either replaces something in the
interpreter or moves to the main core and uses the ULP only for wake/sleep bookkeeping.
