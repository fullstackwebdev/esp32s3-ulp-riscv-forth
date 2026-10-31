# 00 — Background: what the hardware actually is

This document digests the earlier loose notes (chat transcript: "RV32 core with multiply/divide,
8 KB shared between code and data, external FRAM", paging, threads, event loop, Forth sizing) and
separates three things that were mixed together:

1. **Verified facts** — read out of ESP-IDF `v5.4` on this machine, or measured on the board.
2. **Assumptions** — plausible, not yet evidenced. Each one is tagged and turned into an experiment
   in [`02-harness.md`](02-harness.md#7-experiment-queue).
3. **Wrong claims** — the notes contain several. They are listed in the corrections table with the
   evidence that overrides them, so the mistakes do not get re-inherited by the design.

Local IDF tree: `/home/user/research/esp32/esp-idf` (`git describe` → `v5.4`).
Toolchain: `riscv32-esp-elf-gcc 14.2.0` (`~/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119`).
The English **v5.5** page for the same topic was also fetched once and cross-checked against these
sources: no fact used below differs (`probe/EVIDENCE.md`, E-006; cached under `cache/`, key
`2bb0d59988d50b29ecd39e86fd19a164`).

---

## 1. The board on the desk

Detected with `esptool` (read-only `chip-id` / `flash-id`; nothing was written):

| Property | Value |
| --- | --- |
| Chip | ESP32-S3 (QFN56), revision v0.2 |
| Cores | dual Xtensa LX7 + **LP/ULP RISC-V** |
| Max HP clock | 240 MHz |
| Crystal | 40 MHz |
| Flash | 32 MB (`0xC2 0x8039`), off-chip, on the SPI0/1 bus |
| PSRAM | 16 MB **octal**, `AP_1v8`, i.e. the `-N32R16V` style module |
| MAC | `xx:xx:xx:xx:xx:xx` |
| Port A | `/dev/ttyACM0` — `303a:1001` Espressif **USB-Serial/JTAG** (native USB) |
| Port B | `/dev/ttyACM1` — `1a86:55d3` QinHeng CH343 USB-UART bridge (UART0) |

Two independent ports is a gift: flashing/JTAG traffic can own `ttyACM0` while the application
console lives on `ttyACM1`, with no "port busy" dance. See
[`02-harness.md`](02-harness.md#1-topology).

Note both PSRAM and flash are **outside** the ULP's address space (see §2.3). The earlier notes'
external-FRAM question is therefore still open, and it is now a much narrower question than it was.

---

## 2. Verified platform facts

### 2.1 Core and instruction set

| Fact | Value | Source |
| --- | --- | --- |
| ISA | **RV32IMC** + `zicsr` + `zifencei`; hardware mul/div, compressed | `components/ulp/cmake/toolchain-ulp-riscv.cmake`; `docs/en/api-reference/system/ulp-risc-v.rst` |
| Numeric | 32-bit fixed point, no FPU | same doc |
| Register file | standard RV32 x0–x31 (the *FSM* ULP has 4×16-bit regs; RISC-V ULP does not) | same doc |
| Calls into it | ordinary C and assembly, GCC, `-Os`, `--gc-sections` | same |
| In-order, single issue, no caches, no MMU | implied by the memory map; no cache control exists in the ULP API | absence of any API/register |
| Cycle counter | `rdcycle` via `ULP_RISCV_GET_CCOUNT()` | `ulp_riscv/ulp_core/include/ulp_riscv_utils.h` |
| Unsigned/signed div-by-zero | RISC-V defined: quotient all-ones, no trap | RISC-V spec (standard) |

Division and multiplication are single instructions, so a Forth `* / MOD */` should be primitives,
not shift-and-add loops. That part of the notes was right.

### 2.2 Memory: 8176 bytes, not 8192

| Fact | Value | Source |
| --- | --- | --- |
| Region | RTC slow memory (`RTC_SLOW_MEM`), volatile, retained across deep sleep, lost on power loss | `SOC_RTC_DATA_LOW 0x50000000`, `components/soc/esp32s3/include/soc/soc.h:182` |
| Configurable reservation | `CONFIG_ULP_COPROC_RESERVE_MEM`, **range 32 … 8176** on S3 | `components/ulp/Kconfig:29-37` |
| Layout | `.text`, `.rodata`, `.data`, `.bss`, then `__stack_top = ORIGIN + LENGTH` — **one** flat region, code and data share it | `components/ulp/ld/ulp_riscv.ld` |
| Measured | `__stack_top = 0x1ff0` with `RESERVE_MEM=8176` → 16 bytes of the physical 8 KB are unreachable | `probe/` build |
| Loader | `ulp_riscv_load_binary()` **zero-fills the whole reservation**, then copies the blob | `ulp_riscv/ulp_riscv.c:201-217` |
| Loader size check | rejects `size > CONFIG_ULP_COPROC_RESERVE_MEM` with `ESP_ERR_INVALID_SIZE` | same |

Consequences that shape the whole design:

* The budget is **8176 B**, and only 16 B are lost to the loader ceiling. The notes' worry that
  "ESP-IDF reserves a few hundred bytes" is wrong: the measured IDF runtime floor for a real
  application is **128 bytes** (vectors 4, `__start` 16, `rescue_from_monitor` 20,
  `wakeup_main_processor` 12, `ulp_riscv_halt` 36, plus the app).
* Reloading an image is a **cold boot**: every byte of RTC memory is zeroed first. Any state that
  must survive an image swap has to be copied out by the main CPU and back in.
* Because `load_binary` copies a blob, the main CPU can **hot-swap** ULP programs without
  reflashing — the image can be staged in DRAM and pushed at runtime. That is the backbone of the
  harness's fast-iteration loop.

### 2.3 Address spaces: 0x0 and 0x50000000 are the same byte

This is the single most error-prone thing about the platform, and one of the pasted notes got it
half wrong ("symbols land at 0x50000060, so the region starts at 0x50000000").

| View | RTC slow memory | RTC peripheral registers |
| --- | --- | --- |
| Main CPU | `0x50000000` | `0x6000_8000` (RTC_CNTL) etc. |
| ULP | `0x00000000` | `0x8000` (RTCCNTL), `0xA400` (RTCIO), `0xC800` (SENS), `0xEC00` (RTC_I2C) |

Evidence, three independent artifacts:

* `components/ulp/ld/esp32s3.peripherals.ld` — `RTCCNTL = 0x8000`, `RTCIO = 0xA400`,
  `SENS = 0xC800`, `RTC_I2C = 0xEC00`.
* `components/ulp/esp32ulp_mapgen.py` — generated symbols are `ELF address + --base-addr`, and the
  generated file on this build says `PROVIDE ( ulp_main = 0x50000014 )` while the ELF has
  `main` at `0x14`.
* `ulp_riscv_register_ops.h` — `RISCV_REG_CONV()` and the comment "When COCPU accesses the RTC
  register, it needs to convert the access address. When COCPU accesses the RTC memory, dont
  need to convert the access address."

Therefore: pointers exchanged between the two cores **must be translated**, and there must be
exactly one place in the code that does it. The ULP linker script itself links code at `0x0`
(`MEMORY { ram : ORIGIN = 0 }`), so absolute addresses inside the ULP image are already in ULP
space and are consistent — a Forth dictionary of absolute 32-bit addresses works, *as long as* no
`0x50000000`-based pointer ever leaks into it.

### 2.4 Execution model: wake, run, retire

| Fact | Value | Source |
| --- | --- | --- |
| Trigger | RTC_SLOW_CLK timer, or an RTC-IO (GPIO) wakeup | `ulp_riscv_config_wakeup_source()` in `ulp_riscv.c:67-91` |
| RTC_SLOW_CLK default on S3 | docs say **136 kHz**; **measured on this board: 154.9 kHz ± 0.5 kHz**, i.e. the internal ~150 kHz RC (`SOC_CLK_RC_SLOW_FREQ_APPROX`). Use the measured/calibrated value for every tick→µs conversion. | doc macro `{IDF_TARGET_RTC_CLK_FRE: esp32s2="90 kHz", esp32s3="136 kHz"}` in `ulp-risc-v.rst`; **measurement: `probe/EVIDENCE.md` E-011** |
| Core clock | **19.0 MHz ± 0.3 MHz**, derived from 122.6 cycles/tick × 154.9 kHz; IDF's `ULP_RISCV_CYCLES_PER_US 17.5` is 8 % low | measurement, E-011 |
| Timer period field | 24 bits, `RTC_CNTL_ULP_CP_TIMER_SLP_CYCLE` at `[31:8]` → up to 16 777 215 ticks ≈ 123 s | `components/soc/esp32s3/register/soc/rtc_cntl_reg.h:3226-3231` |
| Period API | `ulp_set_wakeup_period(index, period_us)` — microseconds, index 0..4 | `components/ulp/ulp_common/ulp_common.c:20` |
| On every wake | core resets, `reset_vector → __start` sets `sp = __stack_top` and calls `main` | `ulp_riscv/ulp_core/start.S` |
| `.bss` is **not** re-zeroed per wake | zeroing happens once, inside `load_binary` | `ulp_riscv.c:213` |
| Retirement | ULP-side `ulp_riscv_halt()` sets `DONE|SHUT_RESET_EN` and spins — it does **not** stop the timer; returning from `main` calls it | `ulp_riscv/ulp_core/ulp_riscv_utils.c:24-33` |
| Stopping the timer | separate `ulp_riscv_timer_stop()` (ULP side) / `ulp_riscv_halt()` (HP side, different function, same name!) | `ulp_riscv.h:129`, `ulp_riscv.c:181` |
| Wake the HP core | `ulp_riscv_wakeup_main_processor()` → sets `RTC_CNTL_SW_CPU_INT` | `ulp_riscv_utils.c:20-22` |

That combination is exactly what a persistent VM needs: **globals survive across wakes, the C stack
does not, and ordinary `return 0` from `main` retires the core while the timer keeps ticking.** No
special "wake me again" trick is required. (The notes hedged that the wake-up call exists; it does,
and it is a one-register write.)

### 2.5 Concurrency primitives

| Fact | Detail | Source |
| --- | --- | --- |
| No atomic instructions | no `A` extension, no LL/SC, no CAS | `-march=rv32imc` in the toolchain file |
| Shared-memory lock | Peterson's algorithm, IDF ships both sides | `ulp_riscv_lock_acquire/release`, `shared/include/ulp_riscv_lock_shared.h` |
| Lock struct | `{bool ulp, bool main, enum turn}` | same |
| Constraint | HP side is only safe from **one** thread; the doc says so explicitly | `ulp-risc-v.rst`, "Mutual Exclusion" |

So: the main CPU must own exactly one mailbox thread. Inside the ULP, concurrency is cooperative
(§ 8 of the proposal), so no lock is needed between ULP tasks — only between ULP and HP.

### 2.6 Peripherals the ULP can actually touch

| Peripheral | Notes | Source |
| --- | --- | --- |
| RTC_IO / GPIO | RTC-domain GPIOs only (S3: GPIO0…21); level set/get, RTC-IO interrupt | `ulp_riscv_gpio.h`, `ulp-riscv.rst` |
| SAR ADC | `ulp_riscv_adc_read_channel()` | `ulp_riscv_adc_ulp_core.h` |
| Touch pads | `ulp_riscv_touch.h` | component tree |
| RTC I2C master | **SDA must be GPIO1 or GPIO3, SCL must be GPIO0 or GPIO2**; always sends a sub-register address; no FIFO, byte-at-a-time with interrupt polling; no HW atomicity vs. HP core | `ulp-risc-v.rst` |
| Bit-banged UART TX | `ulp_riscv_uart_init/putc`, any TX pin | `ulp_riscv_uart_ulp_core.h` |
| `printf`-ish output | `ulp_riscv_print_install/str/hex` layered on top | `ulp_riscv_print.h` |
| **Interrupts** | IRQ0 internal timer, IRQ1 ebreak/ecall/illegal, IRQ2 unaligned access, IRQ31 RTC peripherals; via Q0–Q3 registers and custom R-type instructions; **no nesting**; IDF currently wires only software-triggered and RTC-IO sources | `ulp-risc-v.rst`, `ulp_riscv_interrupt.h` |
| Flash / PSRAM / SPI0 cache | **not reachable** — nothing in the ULP address window above 0xFFFF | §2.3 mapping |

### 2.7 Debugging: what you do not get

No JTAG, no `printf` to a terminal by default, no breakpoints, no host filesystem. The documented
survival kit is: shared variables in RTC memory, the bit-banged UART, and the trap wake cause
(`ESP_SLEEP_WAKEUP_COCPU_TRAP_TRIG`). Everything the harness does is built on those three plus
direct RTC-memory read/write from the main CPU.

---

## 3. Corrections to the earlier notes

| # | Earlier claim | Verdict | Evidence |
| --- | --- | --- | --- |
| C1 | "8 KB shared between code and data" | ~right: **8176 B** max reservation, 16 B unreachable; measured floor 128 B | `Kconfig`, probe build |
| C2 | "the region starts at 0x50000000" | true for the **main CPU** only; the ULP sees it at `0x0` | `esp32s3.peripherals.ld`, `mapgen --base-addr`, `RISCV_REG_CONV` |
| C3 | "default 90 kHz RC" | wrong for S3 — but the docs' **136 kHz** is also not what this board runs at: **154.9 kHz measured** (the ~150 kHz RC). Both numbers are nominal-versus-actual, and only the measured one may be used for timing. | `ulp-risc-v.rst` macro table **plus** E-011 |
| C4 | "I believe there is a call to wake the main processor, check the docs" | it exists: `ulp_riscv_wakeup_main_processor()` | `ulp_riscv_utils.c:20` |
| C5 | "No hardware instruction supports mutual exclusion, so use Peterson's" | correct, and IDF already ships both halves of Peterson's | `ulp_riscv_lock.h`, `..._lock_shared.h` |
| C6 | "I don't believe this core has Zbb" | correct: `rv32imc_zicsr_zifencei` only | toolchain file |
| C7 | "the ULP can access RTC_SLOW_MEM, RTC_CNTL, RTC_IO, SARADC" | correct, and it can also use touch, **RTC I2C master**, bit-banged UART, and **interrupts** — the notes missed the last two | §2.6 |
| C8 | "an external FRAM would be needed for paging while the HP sleeps" | still possible, but now via a *peripheral*: RTC I2C on GPIO0–3. Not bit-banged, and severely pin-constrained | §2.6 |
| C9 | "FRAM on the ESP32-S3" (first answer) | wrong, and the user caught it. The module has 32 MB flash + 16 MB octal PSRAM, neither visible to the ULP | `esptool` flash-id, §2.3 |
| C10 | "paging only matters for reads, FRAM writes are write-through" | moot without FRAM; and any RAM-resident scheme must respect that `load_binary` zero-fills everything | `ulp_riscv.c:213` |
| C11 | "Forth core in RV32C 2.5–3.5 KB" | plausible but unmeasured; it is a *target*, not a fact | measured by the first ULP build (Q3 in `01-proposal.md`) |
| C12 | "Jupiter Ace shipped Forth in 8 KB ROM + 3 KB RAM" | historically right, but it is a *ROM* — the Ace did not have to fit compiler + dictionary + data in one 8 KB pool | historical, not local evidence |
| C13 | "handlers can miss the next wake; jobs should yield" | worse than that: the ULP is reset on every wake and `sp` is re-initialised, so a handler that overruns simply never retires and its C-stack frame is discarded silently | `start.S`, §2.4; experiment E4 |

---

## 4. What this means for the design

1. **The 8 KB is bigger than the notes assumed.** With a 128 B runtime floor, a token-threaded
   Forth with a real compiler and a working dictionary fits comfortably in RAM alone — which is why
   the resident core is affordable even with 2 KB given over to page frames.
2. **There is no disk, but there is an offline byte server.** Flash and PSRAM are unreachable by the
   ULP directly; they are reachable *through* the main cores. That is now a requirement, not an
   option: see R5–R7 in [`01-proposal.md`](01-proposal.md).
3. **Persistence is the main CPU's job.** Dictionary snapshots, prelude text and paged data live in a
   dedicated flash partition (no NVS); the ULP is the compute engine and the main cores are a byte
   server.
4. **The event loop maps cleanly.** Timer wake → drain events → run tasks → `return` → sleep.
   Globals carry the VM state; the C stack is disposable by construction.
5. **The hard part is the harness, not the Forth.** No JTAG, a ~155 kHz heartbeat, and a 6.46 µs
   RTC tick mean the dev loop must be *batched and framed*, not single-stepped. That is what
   [`02-harness.md`](02-harness.md) specifies.
