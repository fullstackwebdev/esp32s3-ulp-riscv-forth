# Evidence log

Every number that enters a design document gets a line here, with the command that produced it.
Reproduce from the repo root with IDF exported:

```sh
export IDF_PATH=/home/user/research/esp32/esp-idf
. $IDF_PATH/export.sh
```

## E-001 — Board identity (read-only probe)

```
esptool -p /dev/ttyACM0 chip-id
esptool -p /dev/ttyACM0 flash-id
```

```
Chip type:          ESP32-S3 (QFN56) (revision v0.2)
Features:           Wi-Fi, BT 5 (LE), Dual Core + LP Core, 240MHz, Embedded PSRAM 16MB (AP_1v8)
Crystal frequency:  40MHz
USB mode:           USB-Serial/JTAG
MAC:                xx:xx:xx:xx:xx:xx
Flash Memory Information:  Manufacturer c2  Device 8039  Detected flash size: 32MB
```

Ports, from `udevadm info -q property -n`:

| Device | VID:PID | Description |
| --- | --- | --- |
| `/dev/ttyACM0` | `303a:1001` | Espressif USB JTAG/serial debug unit (native USB) |
| `/dev/ttyACM1` | `1a86:55d3` | QinHeng CH343 USB single serial (UART0 bridge) |

`esptool` version 5.3.1 (note: v5 moved to `-p`, not `--port`; `chip_id` → `chip-id`).

## E-002 — ESP-IDF and toolchain

```
cd /home/user/research/esp32/esp-idf && git describe --tags   # v5.4
riscv32-esp-elf-gcc --version                                      # 14.2.0 (esp-14.2.0_20241119)
```

ULP compile flags (`components/ulp/cmake/toolchain-ulp-riscv.cmake`):
`-Os -march=rv32imc_zicsr_zifencei -mdiv -fdata-sections -ffunction-sections`, link with
`--specs=nano.specs --specs=nosys.specs -nostartfiles -Wl,--gc-sections`.

## E-003 — Memory reservation ceiling

```
grep -A9 'config ULP_COPROC_RESERVE_MEM' components/ulp/Kconfig
```

```
default 4096 if !IDF_TARGET_ESP32
range 32 8176 if IDF_TARGET_ESP32 || IDF_TARGET_ESP32S2 || IDF_TARGET_ESP32S3
```

Measured with `CONFIG_ULP_COPROC_RESERVE_MEM=8176`:

```
grep '__stack_top =' build/esp-idf/main/ulp_main/ulp_main.map
0x00001ff0   __stack_top = (ORIGIN (ram) + LENGTH (ram))
```

→ 8176 = 0x1FF0 usable; the physical 8 KB region has 16 bytes the loader will not use.

## E-004 — ULP image sizes (three stock examples, target esp32s3, RESERVE_MEM=8176)

| Example | `.bin` | `.text` | `.rodata` | `.bss` | What it contains |
| --- | --- | --- | --- | --- | --- |
| `ulp_gpio` (poll + wake HP) | **128 B** | 0x80 = 128 B | – | 1 B | vectors 4, `__start` 16, `main` 40, rescue 20, wakeup 12, halt 36 |
| `ulp_gpio_interrupt` | **144 B** | 0x90 = 144 B | – | – | adds the interrupt wiring |
| `ulp_uart_print` (bit-banged UART + print) | **678 B** | 0x27C = 636 B | 42 B | 16 B | UART TX driver + `ulp_riscv_print_*` |

Commands:

```sh
cd probe/ulp_gpio && idf.py set-target esp32s3 && idf.py build
ls -l build/esp-idf/main/ulp_main/ulp_main.bin
grep -E '^\.(text|rodata|data|bss) ' build/esp-idf/main/ulp_main/ulp_main.map
```

Implication for the proposal: the IDF runtime floor is **128 bytes**, not the "few hundred bytes"
assumed in the notes. A bit-banged console costs ~550 B on top, which is affordable but is *not*
free; the ring-buffer console is cheaper.

## E-005 — Symbol addressing: the two address spaces

```
cat build/esp-idf/main/ulp_main/ulp_main.ld
```

```
PROVIDE ( ulp_reset_vector = 0x50000000 );
PROVIDE ( ulp_main        = 0x50000014 );
PROVIDE ( ulp_gpio_level_previous = 0x50000080 );
PROVIDE ( ulp___stack_top = 0x50001ff0 );
```

and in the same build's ELF map:

```
.text.vectors 0x00000000 0x4   reset_vector
.text         0x00000004 0x10  __start
.text.startup.main 0x00000014 0x28  main
```

→ the ELF is linked at 0; the generated header adds `--base-addr 0x50000000` because that is the
**main CPU's** view of RTC slow memory. Confirmed independently by
`components/ulp/ld/esp32s3.peripherals.ld` (`RTCCNTL = 0x8000`, …) and by `RISCV_REG_CONV()` in
`ulp_riscv_register_ops.h`.

## E-006 — v5.5 documentation cross-check

The English v5.5 page for the same topic was fetched once and cached
(`tools/fetch.py`, key `2bb0d59988d50b29ecd39e86fd19a164`, sha256
`28d1dba166e075b09cf762cd2fd2b8820b73c0ab5ea1cdff1b50660322d2900e`, 118 509 bytes, HTTP 200).

Checked against the local v5.4 sources — no differences in any fact used by these documents:
RV32IMC/32-bit fixed point, 136 kHz RTC_SLOW_CLK default for S3, Peterson lock, GPIO1/3 SDA and
GPIO0/2 SCL for RTC I2C, the four interrupt sources (IRQ 0/1/2/31), Q0–Q3 + custom instructions,
the trap wake cause, and the bit-banged UART.

One documentation bug is present in both versions: the "Building Your Project" section tells you to
set `CONFIG_ULP_COPROC_TYPE` to `CONFIG_ULP_COPROC_TYPE_LP_CORE` — that is the C6/H2/P4 LP-core
option. For S3 the correct option (`CONFIG_ULP_COPROC_TYPE_RISCV`) is stated correctly further down
in the same page and in `components/ulp/Kconfig`. Trust the Kconfig.

## E-007 — Token width and dictionary density (probe P02)

Host build, both variants passing the unchanged 53-test suite, 46 definitions:

| Metric | 16-bit tokens | 32-bit xts |
| --- | --- | --- |
| bytes/word, mean | 25.09 | **39.22** |
| bytes/word, max | 60 | 96 |
| definitions straddling 512 B | 4.3–2.2 % | **6.5–8.7 %** |
| definitions straddling 256 B | 6.5–8.7 % | 10.9–15.2 % |
| whole dictionary | 1.0× | **1.49×** |

Literals are 26.5 % of body bytes, headers 44 % of the dictionary. Straddle rate ≈ mean size ÷ page
size, so it is a property of definition size, not of the compiler. Result dir:
`probe/results/P02-token-width/`.

## E-008 — Console, rings and slicing (probe P04)

Host simulation at 115200 8N1. Recommended `(k=4, C=128 B, O=256 B)`, 4 steps/wake, `nchars`=32.

* Zero input and output drops for interactive use and a 100-line paste **in connected mode** (72/72
  rows).
* The same paste in autonomous mode (100 ms) loses **86–96 %** of its bytes at every ring depth that
  fits the 600 B budget ⇒ bulk input must be flow-controlled, not buffered.
* **One token is not one unit of work:** a token calling a colon word with a 100-iteration loop cost
  **505 primitive dispatches** in a single `run()` call, 126× the `k=1` token budget ⇒ the resume
  point must be a **primitive dispatch** (`run_from(w, ip, p)`), not a token.
* `KEY` with an empty ring returns `ERR_NO_INPUT`, pushes nothing, consumes nothing.
Result dir: `probe/results/P04-console-and-slicing/`.

## E-009 — Instruction costs and wake overhead (probe P05, PARTIAL)

Measured on the board with `rdcycle`, 3 runs, spread ≤ 0.03 %:

| Item | Cycles |
| --- | --- |
| dependent `addi` | **4.000** |
| RTC-RAM word load (`lw`) | **8.10** |
| byte load (`lb`) | **8.60** |
| `rd32` cell read (8 byte loads) | **≈ 69** (8.5× a native `lw`) |
| wake entry, reset vector → `main` | **81** |

`cycles per RTC tick` **not obtained**: `RTC_CNTL_TIME_LOW0` is a latched snapshot; `TIME_UPDATE`
must be set and allowed to self-clear before the read, and the first attempt returned a frozen value.
Consequence: D7 in `03-prototype-review.md` becomes a required fix; no absolute wake-budget figure may
be quoted until the tick number exists. Result dir: `probe/results/P05-clock/`.

## E-010 — Engine size and the resident budget (probe P01)

Built through the IDF `ulp_embed_binary` route with an independent re-link producing an identical
blob, `-Os -march=rv32imc_zicsr_zifencei -mdiv`, stub content subtracted via a `-DP01_STUB_ONLY`
control link.

| Item | Bytes |
| --- | --- |
| Engine `.text` | 3556 (upper bound 3566) |
| Engine `.rodata` (63-entry dispatch table) | 252 |
| **Engine total** | **3818** (3.73 KiB) |
| `.data` | 0 |
| Engine `.bss` (stacks, `tib`, scalars) | 222 |
| Stub + startup (`reset_vector`, `pl_emit`, `main`) | 130 |
| Full `.bin` at MEMSZ 2560 | **3948** |

`mem[]` is `.bss`: MEMSZ 2048/2560/4096 give `.bin` 3944/3948/3940, so the Forth array never inflates
the blob. **MEMSZ 4096 does not link against the real 8176 B region** (3948 + 4096 + 290 = 8334 >
8176, `address 0x2086 … not within region 'ram'`), so 4 KB of Forth memory is out of reach.

Budget consequence: **4 frames leave 560 B of dictionary, 2 frames leave 1584 B** — so the frame count
is 2. The 32-bit prelude needs ~1956 B (E-007), a **372 B shortfall** that `01-proposal.md` §4.3 now
records as an open decision rather than a solved number.

R1 item 1 verified on the host: 42 ELF symbols, all C/startup; intersection with the 36 `boot_min.fs`
word names and the system-variable names is empty. Result dir: `probe/results/P01-engine-size/`.

## E-011 — Cycles per RTC tick and core clock (probe P05, closed)

Method: latch the RTC counter (`RTC_CNTL_TIME_UPDATE`, bit 31), poll it clear, then poll the counter
forward by K ticks between two `rdcycle` reads; `cycles_per_tick = span / observed_delta` with the
delta stored rather than assumed. 12–18 independent measurements across 3 K values and 4 phases.

| Item | Value |
| --- | --- |
| cycles per RTC_SLOW_CLK tick | **122.6** (K=1024: 122.541–122.780, 0.20 %; all: 122.093–123.046, 0.78 %) |
| implied core clock | **19.0 MHz ± 0.3 MHz (±1.5 %)** |
| RTC_SLOW_CLK measured | **154.9 kHz ± 0.5 kHz** (phases 153.94 / 154.79 / 154.86 / 154.93) |
| 1 tick in wall clock | **6.46 µs** — *not* 7.35 µs |
| wake entry (reset → `main`) | **81 cycles** |
| usable work in a 1-tick wake | **41 cycles** ≈ 10 dependent ALU ops |

Two documentation corrections, both material:

* The IDF docs' **136 kHz** for S3 is the nominal figure; this board runs the ~150 kHz RC at
  **154.9 kHz** (+14 % over 136 kHz, +3.3 % over 150 kHz nominal). Every tick→µs conversion must use
  the calibrated value (`esp_clk_slowclk_cal_get()`), and RC frequency drifts with temperature — so a
  constant in code would be wrong twice over.
* IDF's `ULP_RISCV_CYCLES_PER_US 17.5` corresponds to 17.5 MHz; the measured core is 19.0 MHz, so
  `ulp_riscv_delay_cycles()` under-delays by ~8 %.

Consequence for `01-proposal.md` §5/§8: a 1-tick period cannot carry a token, so connected mode is
32–64 ticks (207–414 µs), not 1–4 ticks. Result dir: `probe/results/P05-clock/`.

## E-012 — Paging retry: no answer yet, one real bug found (probe P03, PARTIAL)

P03 built the harness (frame table, `resolve()`, fault injection, per-workload runner) but its
exhaustive sweep never ran, so the number that matters is **unknown, not zero**:

| Item | Result |
| --- | --- |
| fault positions tested | **0** |
| mismatches | not measured |
| frames, prelude workload | 2 frames **FAILED** (5 faults), 4 and 8 frames: 1 fault each |
| 12-page workload | not reached (run hung at the first 4-frame case `W1`) |
| `ERR_HOT_SET` | never fired in any completed case (`peak_fpw = 1`) — no data |
| resolve() cost | hit 9.4–9.6 ns, fault round trip 43.7–58.6 ns (host nanoseconds; instruction count not done) |

**Root cause of the empty result: a defect in this repo's fixture, not in the prototype.**
`boot_min.fs` defined `: BASE 12 @ ;`, which returns the *contents* of `V_BASE` rather than its
address. So `HEX` (`: HEX 16 BASE ! ;`) stored 16 into the word at `V_LATEST+2`, destroying the
dictionary link chain: `LATEST 1332 → 1049908`, `BASE → 0`. P03's workload used `HEX`, hence
`err=99` on the baseline. Fixed: `: BASE 12 ;`, with a GUARDRAIL in the file and five regression
tests in `probe/uforth/host_test.c` (suite now 58/58). **P02 and P04 are unaffected** — they never
called `HEX` (only P04's copied fixture *defined* it).

**Design consequence already accepted:** a retry that returns to the same `(w, ip, p)` without an
intervening successful dispatch must abort with **`ERR_PAGE_FAULT_LOOP`**, not spin. P03's hang is
consistent with a retry livelock but the position was not captured, so this is a hypothesis until
P03b tests it.

Follow-up: `docs/probes/P03b-retry-progress.md` — one 200-dispatch workload, 4 frames, every position
injected, progress bound proven. Result dir: `probe/results/P03-paging-sim/`.

## E-013 — REPL line discipline and escapes (probe P10)

Host build with the bridge modelled as a separate object; suite **58/58** before and after.

| Item | Result |
| --- | --- |
| `0x1D` in real + synthetic Forth source | **0 occurrences in 86.1 KB** (22 095 B real + 65 081 B synthetic) — rate 0.00/KB |
| escape table | **6/6** (`ESC ESC`, `f`, `p`, `s`, `q`, unknown → both bytes verbatim, trailing `ESC` flushed after one poll) |
| line discipline | **7/7** (printable, BS, DEL, CR, LF, control bytes ignored+counted, 129-byte line → `ERR_LINE_TOO_LONG` with `HERE`/`LATEST` unchanged) |
| line split across two ring refills | correct, echoed once |
| XOFF | 198 offered / 198 accepted / 198 drained, checksums equal, **0 loss** |
| double echo | none |

Two findings that changed the design rather than the code:

* **F2 — escape must be recognised before the XOFF gate.** Gating the reader on ring occupancy makes
  an escape arriving after the watermark unrecognisable, which breaks `monitor` while input flows.
* **F3 — one number for the line limit and the ring.** The 80-byte line buffer behind a 128-byte ring
  produced errors that looked like ULP faults. Line buffer is now **128 B** (cost 48 B of dictionary).

And one contradiction removed: R8's "a line containing `0x1D` round-trips verbatim" cannot hold,
because the console ignores control bytes by design. There is no literal-`0x1D` escape; binary data
goes through framed payloads. Result dir: `probe/results/P10-repl-host/`.

## E-014 — Primitive-granular page-fault retry is NOT idempotent (probe P03b, FAIL)

One 187-dispatch workload at 4 frames, one fault injected at every dispatch position. Baseline clean
(`err=OK disp=187 faults=15 sp=1 rsp=0 chk=4f99db40`), so this is a mechanism result, not a fixture
artifact.

| Item | Result |
| --- | --- |
| dispatch positions | 187 (fault injectable at **83**; the other 104 have no faultable access, reported as `no_access`, never as passes) |
| positions tested / skipped | 187 / **0** |
| **mismatches** | **32 of 83 (39 %)** — 24 change the page image, 8 change the live stack |
| specimen | position 61: `BUMP` at `w=234`, **one** fault at `ip=1520`, one retry, no cascade — run ends `sp=0` instead of `1` |
| `ERR_PAGE_FAULT_LOOP` on a permanent fault | **fires**, after 5 retries, `w=1430 ip=1432 addr=1430` |
| hangs | **0** (whole sweep 0.2 s) |

Mismatch positions: 59 61 62 73 75 76 77 79 81 82 93 95 96 97 99 101 102 113 115 116 117 119 121 122
133 135 136 137 139 162 174 186.

Mechanism (hypothesis the report names, one experiment from proof): the checkpoint for the token fetch
is taken **before** `w = rd16(ip); ip += 2`, so a fault during that read resumes and re-executes a
dispatch that already completed; and a store performed early in a primitive that faults later in the
same dispatch is repeated.

Design consequence applied: `01-proposal.md` §4.2 rule 2 now specifies **word-boundary pinning** — a
per-definition page list checked once at entry, which is exactly what P02's "≤ two pages per
definition" rule already provides — plus the progress bound above. Result dir:
`probe/results/P03b-retry-progress/`.

## E-015 — P06 wedged the board; the experiment did not run

P06 built and flashed cleanly (bootloader, partition table and app all hash-verified at 12:49:30), then
the board went silent: 0 bytes on `/dev/ttyACM1` and `Write timeout` on `/dev/ttyACM0` from 12:50.

| Attempted recovery | Result |
| --- | --- |
| `esptool -p /dev/ttyACM0 chip-id` | `Write timeout` |
| `esptool --before usb-reset` | `Write timeout` |
| `esptool --before no-reset` | `Write timeout` |
| DTR/RTS control-line reset, CDC drain, `--no-stub` | no effect |
| `udevadm` | device still enumerates (`USB_JTAG_serial_debug_unit`) — the USB peripheral is alive, the chip is not answering |

Requires a **physical** EN press or a USB replug. Consequence: the overrun/timer+GPIO questions are
**unanswered**, not failed. P06 must be re-run after recovery.

One real finding survives, at register level: `RTC_CNTL_ULP_CP_TIMER_REG` (`RTCCNTL+0xFC`) has
`SLP_TIMER_EN` = bit 31, `GPIO_WAKEUP_ENA` = bit 29 and `GPIO_WAKEUP_CLR` = bit 30 as **independent
bits**, so IDF's `ulp_riscv_config_wakeup_source()` choosing one is an API limitation, not a hardware
one. Unconfirmed on hardware, because the readback never reached the host.

Process fix applied to `docs/probes/README.md`: every board probe must keep the image it flashed plus
its `flash_args` as a restorable backup, and must print the recovery ladder when it wedges.
Design fix applied to `docs/02-harness.md` §7b: the bridge task gets an `esp_task_wdt`, and every ULP
`main` retires on all paths, because this failure mode is one bad line away in normal use.

## E-016 — Why primitive-granular retry was wrong: the checkpoint sat before the fetch (probe P03c)

One position (P03b's specimen 61), two traces, host only. Fault-free and retried traces are identical
until the fault, then diverge at the `NEXT` window (`p=3`):

```
base   : CK w=1408 ip=1410 p=3 -> w=174 ip=1412 ... (P_DOCOL ran once, pushed 1488)
retried: CK w=1408 ip=1410 p=3 -> FAULT addr=1410 -> CK w=1408 ip=1410 p=1/2 -> CK w=1408 ip=1410 p=3
         (P_DOCOL runs a second time, pushes 1410)
```

| Item | Value |
| --- | --- |
| cause | **(a)** checkpoint saved before `w = rd16(ip); ip += 2` |
| cause (b) store-before-fault in one primitive | **not present** in this trace |
| re-executed dispatch | `(w=1408, ip=1410, p=3)` = `P_DOCOL` |
| damage | phantom return address `1410` instead of `1488`; `P_EXIT` returns wrongly; body re-runs |
| symptom | 105 dispatch checkpoints vs 95, `sp=0` vs `1`, `chk=e39b261d` vs `4f99db40` |

Design consequence: **the checkpoint moves after the token fetch**, and the cheap design — per-primitive
retry with transient page frames — becomes testable again. That matters because word-boundary pinning
collides with the measured budget: 2 frames (P01) plus definitions that may span 2 pages (P02) means a
straddling definition would hold every frame while it runs. P03d tests whether the moved checkpoint is
sufficient. Result dir: `probe/results/P03c-checkpoint-trace/`.

## E-017 — Recovery after the P06 wedge: UART0 flashes, native USB does not

The board was wedged by P06: `/dev/ttyACM0` enumerated (`USB_JTAG_serial_debug_unit`) but every write
timed out. After the operator pressed EN it re-enumerated (dmesg shows both devices at 12:57/12:58) and
still refused writes — the app was crashing again early, so EN alone returns to the same state.

| Path | Result |
| --- | --- |
| `esptool -p /dev/ttyACM0 chip-id` (native USB) | `Write timeout`, before and after EN |
| `--before usb-reset`, `--before no-reset`, DTR/RTS, `--no-stub` | all `Write timeout` |
| **`esptool -p /dev/ttyACM1 chip-id`** (UART0 via CH343) | **works** — stub uploads, MAC read, hard reset via RTS |

The CH343's DTR/RTS are wired to EN/IO0, so the UART path can force download mode. That makes UART0 the
**recovery port**, and it is now the flashing default in `02-harness.md` §1.

Recovery that was performed: flashed P05's known-good image over `/dev/ttyACM1`
(`--flash_mode dio --flash_freq 80m --flash_size 2MB`, `0x0` bootloader, `0x8000` partition table,
`0x10000` app), then captured 4319 bytes of console output on the same port containing
`mcyc1024=122541` and `hz_milli=154058` — identical to E-011. Board healthy.

**Loss to record honestly:** the firmware that was on the board before this session was overwritten by
P05, which did not take a backup. It is not recoverable. Every board probe now must keep the exact image
it flashes plus its `flash_args` in its result directory.

## E-018 — Checkpoint-after-fetch makes primitive-granular retry correct (probe P03d, PASS)

Same harness and workload as P03b, one change: the resume checkpoint is taken **after** the token fetch
and **before** execution.

| Item | Before (P03b) | After (P03d) |
| --- | --- | --- |
| baseline | `chk=4f99db40 sp=1 rsp=0` | **identical** (the edit moved the checkpoint, not the semantics) |
| positions swept | 187 (83 faultable, 104 `no_access`) | 187, identical counters |
| **mismatches** | 32 of 83 | **0** |
| hangs | 0 | **0** |
| position 61 | `P_DOCOL` pushed `1410` | fault reported in window B with `ip=1488`; `P_DOCOL` pushes `1488` |

All 32 previously failing positions now reproduce the fault-free digest.

Design consequence: **fine-grained retry adopted; word-boundary pinning dropped.** Frames stay transient,
which is what a 2-frame machine needs (P01), and the compiler does not have to emit per-definition page
lists. Remaining gap: no read-modify-write primitive appears in the workload, so "store then fault within
one dispatch" is untested (P03e). Result dir: `probe/results/P03d-checkpoint-fix/`.

## E-019 — Wake timing and wake cause (probe P06, second attempt)

| Item | Result |
| --- | --- |
| overrun model | **drift**: `gap = span_previous_wake + period`, additive term **22 ticks**, constant while span swept 3 → 47 |
| rival models | lost tick → predicts 19 at the overrun points (measured 22); latch → ≈ 0; re-entry → refuted by `cyc_top = 81` on 11 000+ wakes |
| period floor | `ulp_set_wakeup_period(8 µs)` → **22 ticks / 142 µs**; a 1-tick period does not exist |
| timer + GPIO armed together | **yes**, `RTC_CNTL_ULP_CP_TIMER_REG = 0xA0000000` (BIT31 + BIT29), disarmed to 0 |
| wake cause attribution | **0 of 6** — `RTC_CNTL_SLP_WAKEUP_CAUSE` reads 0 on every wake, timer-only included |
| GPIO4 edge latency | **not obtained** — the 142 µs floor swamps a 10 µs poll; needs the pin as sole wake source |
| retire-after-abort | **FAIL** — reproduced the wedge, stage-attributed to the ULP retire path writing `COCPU_CTRL` while the HP disarmed |

The wedge is now explained: run 2 stopped dead after `COEX disarm reg=0x00000000` inside
`retire_phase()`, with a watchdog armed and no panic — i.e. a hardware-level stall from two cores
touching `COCPU_*` concurrently, not a software hang. Recovered over UART0 without touching EN.
Design rule added to `01-proposal.md` §5: **never write `COCPU_*` from the main core while the ULP may
be mid-wake**; stop the ULP by clearing `SLP_TIMER_EN` and waiting for `wake_count` to stop.
Result dir: `probe/results/P06-wake/`.

## E-020 — A dispatch can need three pages at once, and two frames livelock (probe P03e, BLOCKED)

| Item | Result |
| --- | --- |
| fault-free baseline | **livelocks**: `err=ERR_RETRY_CAP … retries=302` after 302 page loads, `baseline_valid=no` |
| positions swept | **0** — no baseline to compare against |
| cycle | three addresses: token page `602`, data `537397248` (PSRAM 1028), inline operand page `1500` |
| progress per retry | **0** — one page load per retry, forever; `ERR_PAGE_FAULT_LOOP` cannot fire because the key alternates `p=1 ↔ p=2` |
| store-then-fault primitives | **0 of 63** by static audit: every store pre-touches its whole byte range |

Two consequences, both applied:

* **4 × 256 B frames** replace 2 × 512 B (same RAM). A dispatch touches up to three pages; two frames
  cannot resolve the cycle and the retry makes no progress. `01-proposal.md` §4.3 updated.
* The "store then fault" risk is **closed by audit, not by sweep** — recorded as an audit with the
  conditions under which it must be re-checked.
Result dir: `probe/results/P03e-store-then-fault/`.

## E-021 — Engine at 32-bit refs + paging (probe P12)

| Item | Value |
| --- | --- |
| engine `.text` / `.rodata` | 3734 / 252 = **3986 B** |
| delta vs P01's 3818 | **+168 B (+4.4 %)** — `pg_load` 108 + `rd32_paged` 70 |
| 32-bit width alone | ~free in the engine; the growth is paging helpers |
| frames + page table in `.bin` | **0 B** (1040 B of `.bss`, proved three ways) |
| `.bin` at MEMSZ 2560 | 4116 B |
| headroom / spare (2 × 512 frames) | 1416 B / **−266 B after the 48 B line buffer** |

Also: image + `.bss` is 8006 of 8176 at `MEMSZ` 2560 — **32-bit refs and ≥ 4 KB of Forth memory cannot
both be paid for**. Result dir: `probe/results/P12-engine-32bit/`.

## E-022 — Stack depth (probe P13, PASS)

Instrumented at `SD=256` so nothing is capped:

| Workload | data | return |
| --- | --- | --- |
| prelude compile | 3 | 2 |
| 5-deep nested `IF`+`DO` compile | 6 | 2 |
| 3-level nested `DO` with `I`/`J` | 2 | **7** |
| `."` 60 chars, `TYPE` 60 chars | 2 | 1 |
| `find`/`number`, 30-char token, 200-word dict | 1 | 0 |
| line of 20 numbers | **20** | 0 |
| 100-iteration loop through two words | 2 | 4 |

**Peak 20 + 7 = 27 cells = 108 B.** The 400 B stack line had 3.7× headroom; it is now **128 B** and the
difference goes to the dictionary. Compile-time depth is *below* runtime and scales with source nesting,
not program size, so the compiler does not need its own stack. Result dir: `probe/results/P13-stack-depth/`.

## E-023 — Cycles per dispatch (probe P14, PASS)

Static accounting on the rv32 build, weighted by P05's measured instruction classes.

| Path | Cycles |
| --- | --- |
| `rd8` | 36.6 |
| `rd16` / `rd32` (byte-wise) | 177.8 / **452.2** |
| **`NEXT`** | **480.2** |
| dispatch head (code-field fetch, bounds, jump table) | 496.3 |
| `DUP` / `DROP` body | 122.0 / 29.2 |
| `@` byte-wise vs native `lw` | **517.0 vs 64.9 (8.0×)** |
| `P_DOCOL` / `P_EXIT` | 69.3 / 65.3 |
| `0BRANCH` not-taken / taken | 69.3 / **533.5** |
| **dispatch best / typical / worst** | **1 006 / 1 074 / 1 506** |

Consequences: 4-token typing slice **35 ticks (226 µs)**; one prelude line 113 µs; P04's 505-dispatch
token **4 424 ticks (28.6 ms)**. `NEXT` + dispatch head is **90.9 %** of a dispatch, and it is dominated
by two byte-wise `rd32` fetches — so D7 is the highest-value change in the project. Result dir:
`probe/results/P14-cycles-per-token/`.

## E-024 — 4 × 256 B frames do not work; 4 × 512 B is the minimum that boots (probe P03f, FAIL)

| Layout | Prelude | RMW workload | Sweep |
| --- | --- | --- | --- |
| 2 × 512 (P03d) | compiles | **livelocks** (302 retries) | 0 mismatches |
| **4 × 256** | **`ERR_RETRY_CAP` while compiling** | not reached | not measured |
| 4 × 512 | compiles | livelocks (reproduces P03e) | 0 mismatches over 187 |

Distinct pages in the worst cycle: **3** at 512 B (`602`, `1500`, `537397248`); **3** at 256 B too
(`508`, `764`, `1024`) but against only 2 evictable slots, so it thrashes. The rule is
**frames ≥ N + 1** where N is the pages a dispatch touches, and **shrinking pages raises N**, so the
budget cannot be recovered by making pages smaller. Frames are now **4 × 512 = 2048 B**. Result dir:
`probe/results/P03f-frames-4x256/`.

## E-025 — Operand co-location does not reduce N (probe P19, FAIL)

Compiler padding rule: pad to the page boundary so a token and its inline operand always share a page.
It works, and it is nearly free:

| Layout (rule in place) | prelude | workload | max N |
| --- | --- | --- | --- |
| 4 × 512 (control) | compiles | completes, sweep clean 0/187 | **3** |
| 3 × 512 | compiles | **dies**, `ERR_RETRY_CAP ti=4 addr=1530` | 3 |
| 2 × 512 | **cannot compile** | — | — |
| 4 × 256 | **cannot compile** (`ti=12 addr=764`) | — | — |

Padding cost: **6 B in the prelude (0.46 %)**, 12 B (0.80 %) in the RMW build.

**But N stays 3, and the third page is the data/cell page** — cycle `602 / 1500 / 537397248` is two
code pages plus data page 1028. No compiler rule can merge a data page with a code page, so frames stay
**4 × 512 = 2048 B** and the 512 B that §4.3 is short has to come from another line. Result dir:
`probe/results/P19-operand-colocation/`.

## E-026 — Trimming the primitive set is the decisive lever (probe P20, PASS)

| Variant | engine `.text` | engine total | prelude dictionary | dispatch cycles |
| --- | --- | --- | --- | --- |
| A baseline | 3734 | **3986** | 1956 | 1 074 (P14 basis) |
| B native `lw`/`sw` | 3850 | **4102** | 1956 | **807 — 0 saved** |
| C + 40 primitives | 2982 | **3162** | **1716** | **726** (658 best / 994 worst) |
| D + prelude resident | 2982 | 3162 | 1716 of 2560 | 726 |

Variant A reproduced 3986 B exactly, which validates the comparison; the host dictionary cross-check
reproduced P02's 1956 B.

* **Trim 64 → 40 primitives: −824 B engine, −240 B dictionary.** The single biggest win measured.
* **Native accessors: +116 B and 0 dispatch cycles** — token fetch uses `rd32_paged()` (page resolve
  once, then four `lbu`), never the byte-wise chain. D7's 8.0×/5.5× applies to `@`/`!`/`find`/`mkhdr`,
  i.e. parse and compile.
* **A page miss costs ≈ 18 700 cycles ≈ 0.99 ms — 26× a dispatch.** Paging policy, not instruction
  choice, sets the wake period.
* Variant C consequences: typing slice **23.7 ticks / 153 µs**; one prelude line **76.5 µs**; a
  505-dispatch token **2 990 ticks / 19.3 ms**.
* Variant D (prelude resident, with headers) is **348 B short** of the old headroom — which is why
  headerless names matter. Result dir: `probe/results/P20-native-accessors/`.

## E-027 — C stack is 244 B worst case, not 400 (probe P21, PASS)

| Item | Value |
| --- | --- |
| largest single frame | `main`, 96 B (the whole engine is one inlined 3140 B function) |
| deepest static chain | `main` 96 → `clit` 16 → `cw` 32 → `rd32` 16 → `rd16` 16 → `rd8` 0 = **176 B** |
| tied chain | `main` → `find` 48 → `rd32` → `rd16` → `rd8` = 176 B |
| interrupt save (`SAVE_REGS`) | **68 B** on the same stack |
| **worst case** | **244 B** |
| host verification | observed 368 B against a 464 B static bound — the rule never understates |
| **recommended** | **320 B** (76 B margin) |

§4.3's C-stack line drops 400 → 320, returning 80 B to the dictionary. Result dir:
`probe/results/P21-c-stack/`.

## E-028 — The machine links, with 94 bytes to spare (probe P22, PASS)

Built exactly as §4.3 specifies: 40 primitives, 32-bit refs, 4 × 512 B frames, 128 B Forth stacks,
320 B C stack, 128 B line buffer, headerless resident dictionary, names in a paged directory.

| Item | Value |
| --- | --- |
| engine `.text` / total | 3010 / **3190** (`.rodata` 180) |
| resident dictionary after headers move | **1104 B** (612 B of header bytes removed from the 1716 B dictionary) |
| name directory (paged) | **812 B** for 78 definitions |
| `MEMSZ` that links | **1188 B** (predicted 1380) |
| link at 1380 | **fails**: `address 0x1f6e … not within region 'ram'`, 8046 vs 7856 = **190 B over** |
| leftover | **94 B total** (10 B pool + 84 B inside `MEMSZ`) |

The 202 B gap between prediction and reality is named: **142 B of ULP hook/REPL glue with no budget
line**, 28 B of engine growth from the `MEMSZ` constant folding into access paths, 22 B alignment, 10 B
residue.

**Method warning worth keeping:** the first link "passed" with 880 B of spare because four budget arrays
had been **dead-store-eliminated** out of `.bss` (728 B). `nm -S` caught it; the arrays are now
volatile-touched and symbol-visible. Any future budget build must confirm allocation from symbols, not
from a successful link.

Consequence: **no room to grow** — everything above the prelude (tasks, event loop, REPL words) lives in
paged storage. Result dir: `probe/results/P22-fits/`.

## E-029 — A page fetch costs 144 µs, and two in flight corrupt silently (probe P16, PARTIAL)

| Config | median | p95 | max |
| --- | --- | --- | --- |
| **A** awake, polling (200/200) | **22.35 ticks / 144 µs** (2 740 cyc) | 22.84 / 147 | 23.41 / 151 |
| **B** awake, blocked on a ULP signal | **not measured** — doorbell `isr_count = 0`, 200/200 timed out, tried both GPIO and RTC mux | — | — |
| **C** deep sleep, woken, booted | **not measured** — wake path not in that image | — | — |

* Transport is deterministic (spread 1.07×), **3.55 MB/s** sustained for 512 B fetches.
* **P20's 18 700-cycle estimate was 6.8× too high.** Lower bound caveat: the page came from internal RAM,
  PSRAM was not enabled in the inherited build.
* Break-even: 2 740 / 122.6 = **23 ticks**; fault + dispatch ≈ 30 ticks; typing slice + fault ≈ 53 ticks.
* Failure modes, all detectable and named: server stopped → `TIMEOUT_NO_ANSWER` after ~158 ms (no hang, no
  zero-fill); bad CRC → `CHECKSUM_REJECTED`; out-of-range → `RANGE_REJECTED`, nothing copied.
* **Two requests in flight → `TWO_IN_FLIGHT_CORRUPT`: the `seq=1` reply for page 0 carried page 1's bytes
  with a valid checksum.** CRC cannot catch this; only a page marker did. The protocol must enforce a
  single outstanding request.
* The doorbell path (`ulp_riscv_wakeup_main_processor()` → a blocked HP task) **does not work as built** —
  that is the next probe, because the byte server depends on it.

Result dir: `probe/results/P16-page-fetch/`.

## E-030 — Waking the main core works (probe P23, PASS)

Correct mechanism: `ulp_riscv_wakeup_main_processor()` → `RTC_CNTL_SW_CPU_INT` →
`RTC_CNTL_COCPU_INT_ST`, handled by `ulp_riscv_isr_register(fn, arg, ULP_RISCV_SW_INT)`.

| Path | fired | median | p95 | HP task |
| --- | --- | --- | --- | --- |
| ISR → blocked task (semaphore) | **200/200** | **27.32 ticks / 176 µs** | 27.71 / 179 | blocked |
| light-sleep wake | 200/200 | 73.43 ticks / 474 µs | 74.65 / 482 | asleep |
| deep-sleep wake | 1/2 staged | not measurable — the chip reboots | — | asleep |
| polling (control) | 200/200 | 24.25 ticks / 157 µs | 24.90 / 161 | spinning |

P16's failure explained: it drove an RTCIO pad and hung a **digital** GPIO interrupt off it — 0 ISRs in 200
edges. Register evidence after every pass: `INT_ST=0x00000000`, `swcpu_pending=0`, `hp_isr=200` for 200
requests, so latches clear and nothing leaks. Doorbell costs **20 µs over polling** and lets the core
block. Result dir: `probe/results/P23-doorbell/`.

## E-031 — The OS layer is 5.9 frames and the idle loop thrashes (probe P24, PASS/FAIL)

Measured on the compiled layer (80 definitions, Forth, against the shipped 40-primitive set):

| Group | defs | headerless bytes |
| --- | --- | --- |
| tasks | 39 | 1380 |
| events | 20 | 908 |
| REPL | 9 | 300 |
| introspection | 8 | 348 |
| device | 4 | 108 |
| **total** | **80** | **3044 (5.9 frames)** |

10 definitions per 512 B frame (3–15 spread); `POLL-EVENTS` alone is 320 B = 62 % of a frame.

| Workload | pages | faults |
| --- | --- | --- |
| **idle event loop** | **7** (corrected, P25) | **13 per pass, 1 872 µs → thrash** |
| line calling three OS words | 8 | 8, 1152 µs → thrash |
| compiling one definition | 3 | 3 once, then stable |

94 B of resident room holds no executable word (smallest is 16 B; three 32 B task records are 96 B).
So R3 and R4 are **not met** by this layer on this machine. Result dir: `probe/results/P24-os-layer/`.

**Correction (P25):** the page and fault figures above were **analytic**, computed from where the named
definitions *sit* (`cf//512 … end//512`) and turned into ">4 pages ⇒ thrash" by hand — no tracer was used.
P25 built a real tracer through `resolve()`/frames and re-measured: **7 pages, 8 570 accesses per pass, 13
faults per pass**. The published number was conservative (1 page low, faults 2× low), so the verdict holds,
but the method did not deserve to be called a measurement.

## E-032 — A 1024 B OS layer runs the idle loop fault-free (probe P26, PASS)

Written to the **literal** content of R3 and R4 rather than the spirit: 22 definitions, **1024 B
headerless (exactly 2 frames)**, 1224 B with headers, 200 B of headers, 40 B of data, 192 B of task stacks
outside the count. P24's layer was 3044 B for 80 definitions — **66 % removed**.

| Group | budget | actual |
| --- | --- | --- |
| tasks | ≤ 300 | 292 |
| events | ≤ 250 | 304 (guard + `DIAG` kept deliberately) |
| REPL | ≤ 200 | 188 |
| introspection | ≤ 120 | 240 (`WORDS` 136 + `U.` 80 + `.S` 24 is the floor; no decimal printer in the primitive set) |
| device | ≤ 100 | 0 (`GPIO@`/`GPIO!` are primitives) |

Workloads, 4 × 512 B frames — **re-measured with a real access tracer (P25)**: idle loop touches **2 layer
pages (3, 4), 2 faults on the first pass, 0 faults per pass steady**, 2 510 accesses per pass. A line calling
three OS words: 0 steady. Compiling a definition: stable after the first pass. P26's own figures were
analytic (3 pages); the traced number is *better*, not worse.

Context for the trace: **90 % of the accesses are instruction fetch** (7 670 of 8 570 in P24's loop), and
**41 % of P26's accesses land on pages 0–2** — the resident region. So the real working set is "two code
pages plus the resident core", which is exactly what 4 frames buys.

**Probe-found bug in its own draft:** `YIELD` returned the new slot, so `SLEEP-TICKS` leaked a stack cell
per iteration — compiles clean, corrupts the stack after 16 passes. Fixed, guarded, and every word was
hand-traced for stack neutrality.

**Caveat:** `dsp`/`rsp`/`ip` are C statics, so the scheduler switches records but not the machine. R4
remains bookkeeping until the resumable interpreter exists.
**Also under re-check (P25):** the page tracer may not have counted instruction fetches, which would affect
both this and P24's counts. Result dir: `probe/results/P26-minimal-layer/`.

## E-033 — A context switch works inside a colon word, and costs 140 B/task (probe P27, PASS)

| Item | Value |
| --- | --- |
| VM state per switch | `ds[SD]` by value (64 B at `SD=16`), `rs[SD]` (64 B), `sp`, `rsp`, `w`, `ip` = **136 B** |
| record per task | **140 B** (136 + 4 B record); **268 B at `SD=32`** |
| three tasks | **420 B** (`SD=16`) or **804 B** (`SD=32`) |
| not saved | `run()` temporaries (dead across a dispatch); `tib/ti/tl/errf` (outer interpreter, still not resumable) |

Four predictions, each computed on the host from the scheduling rule and Forth arithmetic, never from VM
output — all matched exactly:

| Test | Predicted | Actual |
| --- | --- | --- |
| (a) three-task interleaving | order `A>B>C>A…`, counts 5/3/4, 15 switches | identical, 5/3/4, 15 (12 pause + 2 exit + 1 entry), max C nesting 1 |
| (b) suspend mid-word | 676, image byte-identical to no-`PAUSE` | 676, digest `0xfc3c37f0` identical, 1 suspend |
| (c) `PAUSE` in `DO` in a word | 10, digest of the no-`PAUSE` word, 5 resumes | 10, `0x2895577b` identical, 5 suspends |
| (d) page fault at the same positions | same digests | 676 after 1 retry, 10 after 5 retries |

**`PAUSE` and the page-fault path are one mechanism** (`vm_switch`, the only code that copies a `VM`).

Budget consequence: R4 costs **420 B** that the linked machine does not have (94 B spare). Result dir:
`probe/results/P27-resumable/`.

## E-034 — Pin edges latch through sleep and coalesce to one per wake (probe P18, PASS)

| N edges during one sleep | status bits | events |
| --- | --- | --- |
| 2 / 5 / 50 / 500 / 5 000 | 1 (GPIO4 = bit 14) | **1** in every case |

| Edge rate | sent | events | lost | lossless |
| --- | --- | --- | --- | --- |
| 1 Hz | 3 | 3 | 0 | yes |
| 100 Hz | 200 | 151 | 49 | no |
| 10 kHz | 1 000 | 7 | 993 | no |
| 100 kHz | 1 000 | 1 | 999 | no |

`events == wake intervals` in every saturated case ⇒ the ceiling is **one event per pin per wake** = 151
edges/s at a 1 s period (1 023 measured ticks, 6 608 µs, +2.3 % over the request). Single pulses down to
**30 ns** still latched (8/8). Latency = period − edge phase, uniform: min 990 / median 4 188 / max 6 592 µs,
never more than one period. Latch found set at the next wake in **13/13** trials and reads `0x00000000`
after clearing, with zero events over three quiet wakes.

So the event ring needs **one bit per pin per wake**; a per-pin queue is wrong. Result dir:
`probe/results/P18-edge-coalescing/`.

## E-035 — R4 closes only with 16-bit code tokens (probe P28, PASS)

Each extra task takes 140 B from the same pool, so `MEMSZ` falls as tasks are added. Measured with both
images actually built and walked (78 definitions, identical set):

| # | tasks | `MEMSZ` | resident need | gap |
| --- | --- | --- | --- | --- |
| A | 1, 32-bit | 1188 | 1104 | +84 |
| B | 2, 32-bit | 1048 | 1144 | **−96 fails** |
| C | 3, 32-bit | 908 | 1144 | **−236 fails** |
| **D** | **3, 16-bit** | **908** | **676** | **+232** |
| E | 3, 16-bit, cold prelude paged | 908 | 448 | +460; page claim untraced, not needed |
| F | 3, 16-bit, `SD=12` | 976 | 676 | rejected — `SD` must be a power of two, and 12 < P13's 20-cell peak |

16-bit dictionary: **636 B resident** = 56 B header + 496 B prelude + 84 B primitive headers; bodies
728 → 424 B (1.72×, P02 measured 1.74×); code fields 312 → 156 B; name directory a wash (812 → 818).
The 32-bit image reproduced P22 exactly (1716 B compiled, 1104 resident, 812 directory).

Adopted: **16-bit code tokens, 32-bit data cells.** No measured margin is spent — frames stay 4 × 512 B,
stacks `SD=16`, C stack 320 B, rings 600 B, all 78 words resident. The cost is a 64 KB *code* ceiling
(~1 600 words vs a 78-word prelude); data addressed by 32-bit cells is unaffected.
Result dir: `probe/results/P28-pay-for-r4/`.

## E-036 — The shipping engine is 1836 B over the pool (probe P29, FAIL)

Built as specified — 16-bit code tokens, `vm_switch`, paging, four real hooks, 3 × 140 B task records — and
linked. It does not fit:

| Item | Value |
| --- | --- |
| engine `.text` / `.rodata` / total | **4670 / 264 / 4934** |
| delta vs P22's 3190 | **+1744** |
| region need | **9692 vs 7856 → 1836 over** (`address 0x25dc … not within region 'ram'`) |
| `MEMSZ` 0 | **still 918 B over** ⇒ the pool binds, not the dictionary |
| `nm -S` allocation | **confirmed for every array** — nothing eliminated |

Attribution: `vm_enter` **2380 B (51 %)** = 61 primitive bodies *plus* `resolve`/`pg_load` inlined at every
stream read; libgcc `memcpy`+`memset` **400 B** (from `tsk[from].vm = *V` and the init zero loop);
`vm_switch` 102; `pg_load`+`rd16_paged` 168; `word`/`find`/`mkhdr`/`err`/`clit` 598; hooks 196.
Cleared: no double stack copy, the fault path shares `vm_switch`, hooks are small.

Derived target: for a 4-frame, 3-task machine the **engine budget is 3438 B**, so **1496 B must come out of
code structure**. Result dir: `probe/results/P29-shipping-engine/`.

## E-037 — Code structure is not the lever; the primitive count is (probe P30, FAIL)

Five builds of the same source, engine measured as sections (`.bin − control` is +14 B in every row), with
`nm -S` confirming every budget array present in **all five**:

| Variant | engine | `vm_enter` | libgcc | Δ vs A |
| --- | --- | --- | --- | --- |
| A baseline | **4934** | 2380 | 400 | — |
| B `noinline` paging helpers | **4934** | 2378 | 400 | **0** |
| C + 62 primitive bodies out of line | **6120** | 668 | 400 | **+1186** |
| D + hand VM copy / zeroing | **5756** | 668 | **0** | +822 |
| E + `-fno-tree-loop-distribute-patterns` | **5756** | 668 | **0** | +822 (identical) |

All five fail a real 7856 B link (A/B 1836 over, C 3020, D/E 2656).

The hypothesis tested — "one inlined dispatch function is the bloat" — is **disproved**: out of line the
bodies cost **2872 B** plus a 668 B switch = **3540**, against **2380** inlined. Per primitive body the cost is
~57 B wherever it lives. The only structural win is libgcc: `vm_copy` (30 B) replaces `memcpy` (232 B) and a
4-word-unrolled zero loop removes `memset` (168 B).

Consequence: the lever is the **primitive count**, not the code shape. Result dir:
`probe/results/P30-code-structure/`.

## E-038 — The derived primitive set is 40, the engine 3412, and the link 296 B short (probe P31)

Derived, not guessed: a host build with `-DP31_TRACE` recorded the header address of **every name lookup**
while `boot_min.fs` and all five P26 layer files loaded through the real interpreter → **35 primitives**;
plus 5 emitted directly as tokens and never looked up (`EXIT`, `LIT`, `DOCOL`, `DOVAR`, `DOCON`) → **40**,
which is exactly P20's set. (The steering's `nm`-diff cannot answer this: both builds keep every body inside
one function, so `comm` yields only machinery and zero primitive symbols.)

| Variant | primitives | engine | real link at 7856 |
| --- | --- | --- | --- |
| A | 61 | 4934 | fails, 1836 over |
| B | 40 | 3454 | fails |
| **C** | **40 + libgcc fixes** | **3412** | **fails, 296 over** (8152 needed) |

**The 3438 B target was itself optimistic by 322 B**: the fixed lines measure 4740, not 4418, so the true
engine ceiling is **3116 B**.

**Functional cost of the derived set — the more important result.** Deriving from current usage is circular: it
keeps only what today's code calls, so the machine can run the program it was measured on and little else. The
40-set drops `I`, `J` and `UNLOOP`, so **a user cannot write `DO … LOOP`** despite the prelude defining it; drops
`GPIO!`, so **nothing can drive an output**; and drops `'`, `(`, `."`, `CONSTANT`. Restoring what the language
needs puts bytes back. Result dir: `probe/results/P31-primitive-set/`.

## E-039 — The 322 B is a convention error, and only dropping paging closes the gap (probe P32)

Every byte of the discrepancy attributed from `nm -S` on P31 variant C's image:
`+420 tsk + 196 startup/entry + 128 tib + 34 statics + 6 counters − 142 hooks − 320 C stack = 322`.
The table's arithmetic was right; its **conventions** were not — it counted a *code* line (hooks) among
allocation lines, counted a line **not in the image** (the C stack, which grows down inside the region because
`__stack_top = ORIGIN + LENGTH`), and omitted three real allocations (task records, startup, line buffer).

* Corrected engine ceiling: **3116 B**; **2796 B** once the C stack is honoured inside the pool.
* **Variant D** (language restored: `I J UNLOOP GPIO! ' CONSTANT ( ." (.")`) → engine **3916 B**,
  region need **8656 of 7856 = 800 B over** (1120 if the stack is reserved). The nine entries cost **504 B**.

| Option | Frees | Residual | Cost |
| --- | --- | --- | --- |
| **(a) drop paging from v1** | **−2466** | **fits, 1666 B spare** | no frames, no paged fetch, no fault retry; language unchanged, re-addable later |
| (b) two tasks | −140 | 660 short | R4 → 2 tasks |
| (c) `mem` → 676 | −232 | 568 short | zero dictionary slack; (b)+(c) still 428 short |

Only (a) closes alone. Result dir: `probe/results/P32-audit-budget/`.

## E-040 — The program is 1008 B / 36 words, not 232 B / 8 (probe P35)

Measured by construction: raise `MEMSZ` until the link fails, and report the largest value that links.

| Case | `MEMSZ` links | fails at | operator's budget (−676 prelude −512 buffer) | words @28 / @39 |
| --- | --- | --- | --- | --- |
| paged machine (P28) | 908 | — | 232 B | ~8 / ~6 |
| **non-paged, C stack not reserved** | **2196** | 2197 | **1008 B** | **36 / 25** |
| non-paged, C stack reserved (LENGTH 7536) | **1880** | 1881 | **692 B** | 24 / 17 |

`nm -S` at 2196: `mem = 0x894 = 2196`, and **`frm`, `ptab`, `ptab_lru_reserve` are GONE**; `tsk` 420, `tib` 128,
`mailbox` 216, rings 384, `vm_live` 136, `blk_out` 4 all present. The block layer costs **352 B** total (348
engine + 4 `blk_out`), 152 B over the 200 B the probe had reserved for it.

Section arithmetic closes the books: `sections = 5651 + MEMSZ` (non-paged) vs `7748 + MEMSZ` (paged), so
**2091 of the 2466 B returned** and 352 was spent — every byte accounted for.

The probe also refused to repeat P32's convention error: because the 512 B block buffer lives *inside* `mem[]`,
it reports `MEMSZ − 676` **and** `MEMSZ − 676 − 512`, and quotes the latter as the operator's budget.
Result dir: `probe/results/P35-program-size/`.

## E-041 — Transparent access costs 888 B of dictionary; explicit costs 202 (probe P34)

| Shape | Dictionary | Fits 1008 B app space |
| --- | --- | --- |
| `@` `!` `C@` `C!` shadowed to page + machinery | **888 B** (636 headerless) | no — ~120 B left |
| `F@` / `F!` only | **202 B** | yes — ~806 B left |

Engine: **+244 B** over the non-paged build (4174 sections; `far_xfer` +144, `far_sum` +50, `pl_hw` de-inlined
+126, minus `pg_load` −108 and `rd16_paged` −60). **The real 7856 B link succeeds, using 3369 B.** The block
buffer is its own 512 B `.bss` array, so `mem` stays 908.

Shadowing proof is **half**: pre-existing words keep the raw primitive (token = xt; `@` header 230 → xt 234;
a word compiled later installs at 2220 with `' @` = 2220), but the shadow failed to install inside `paging.fs`
(`ERR_UNNAMED`, `' @` still 234, 78 B of orphaned body bytes), so the "user code pages transparently" half was
never demonstrated. Result dir: `probe/results/P34-forth-paging/`.

## E-042 — Visible blocks link with 785 B spare and cost 456 B of Forth (probe P33)

| Item | Value |
| --- | --- |
| engine | D 3916/3928 → E **4096 sections / 4110** (`.bin − control`); like-for-like **+200 B** vs D |
| transparency removal | −168 B (`pg_load`, `rd16_paged` both absent from `nm`) |
| layer's own C | **≈ +366 B** (`vm_enter` +170, `blk_sum` +50, `.rodata` +32) — above the 200 B guideline |
| buffer | **512 B inside `mem[]`** at `MEMSZ−512`; a separate array would be unreachable by `C@`/`!` |
| region need | **7071 of 7856** — the link **succeeds**, where transparent paging was 800 B over |
| spare | **785 B**, or **465 B** with the C stack honoured |
| Forth layer | **456 B** measured by watermark (888 → 1344) — **432 B cheaper than P34's 888 B** |

Host execution: the **protocol** passes 4/4 (read returns the right bytes, `SAVE` writes back, named failures
fire); the **Forth wrappers `BLOCK` and `SAVE` hang**. Candidate causes: the host harness has no concurrent
server to service a synchronous spin (would work on the chip), or a real branch/operand bug at that `HERE`.
Unresolved — P37.

Result dir: `probe/results/P33-visible-blocks/`. (The probe also disclosed a brief use of `/tmp/x.fs`, against
the project rule; recorded as a discipline lapse, not hidden.)

## E-043 — Overlays work; the loader does not fit (probe P36, mechanism PASS / budget FAIL)

| Item | Value |
| --- | --- |
| segment buffer | 512 B at Forth address 4096 = `MEMSZ` (P34's `far_buf`, no C change) |
| loader + directory + 12 inline `ERR_*` strings | **1 400 B resident** (HERE 2 228 → 3 628) |
| maximum `MEMSZ` that links | **2 196** |
| **app space left** | **−1 432 B** |

Dictionary ladder, measured: primitives 630 → `+control` 1 038 → `+pre` 1 328 → `+paging` 2 228 → `+seg` 3 628.

Execution: (a) compile→save→clear→reload→execute **passes** (same result), (b) the reloaded body calls resident
`=`/`IF`/`.` **passes** (`7 SQ 49 =`), (c) a second segment swaps in and runs **passes** (the first entry slot now
reads 16178 where 4100 was), (d) the stale-segment *refusal* **never ran** — the gate line aborted with a stack
underflow because `EXECUTE` on a bare token list pops a return frame nobody pushed, (e) the resident-token
equality was inconclusive (the probed cell was a `LIT` operand, not a token).

Two corrections to earlier figures: **app space is 620 B, not 1 008** (P35 never charged the block layer, which is
900 B in this variant), and a segment entry must be a real colon definition (carrying `DOCOL`) for `EXECUTE` to
work. Result dir: `probe/results/P36-overlays/`.

## E-044 — The block layer's hang was three bugs in the Forth, not the engine (probe P37)

Cause **L**, at three named places. Cause H (harness has no concurrent server) is **refuted**, not merely
unconfirmed: `blk_xfer` calls `pl_hw(6,…)` — the host's `srv_answer()` — *before* its poll loop, so the server was
always serviced inside the word.

| # | Bug | Effect |
| --- | --- | --- |
| 1 | `boot16.fs` `IF`/`ELSE` emit the branch **token** with `,` (P_COMMA: 4 bytes, 4-aligned) where `ZBRANCH` reads a **2-byte** operand | every compiled `IF` read its target from a `0x0000` filler; at 2 mod 4 it executed a `0x0000` hole in front of the token as `DOCOL` at address 0, so `rsp` climbed 2,3,4,… |
| 2 | `BLOCK`'s `0= IF DROP 0 BLKDRT ! EXIT THEN` | `0=` works on TOS only, so `DROP` removed the **buffer address** and `BLOCK` returned nothing; the caller's `!` popped an empty stack, `sp` → 255 |
| 3 | `SAVE` | same stack-order slip, status lost |
| 4 | P33's host `MEMSZ=2304` placed the 512 B buffer at 1792 while the test dictionary reached 1842 | the fetch **overwrote definitions** |

Experiments that established it: a plain-variable spin terminates (so compiled loops work and the harness can run
them); the real wrapper completes **8/8** once the server is serviced inside the word; a Forth-level bounded wait
reaches `ERR_NO_SERVER` at four polls (`BLKERR=-3`) instead of hanging.

Lesson: a 16-bit engine takes a 2-byte branch operand, and `,` is not `W,`. Result dir:
`probe/results/P37-block-wrapper/`.

## E-045 — The block layer is correct (probe P38, PASS on all five)

| Proof | Result |
| --- | --- |
| (a) compiled `IF…ELSE…THEN` × 4 nesting levels, `BEGIN…UNTIL` × 4 | **17/17** — leaf index `8d+4c+2b+a`, because Forth's branch consumes TOS (the *last* argument). The first run failed 12/16 and the **model** was wrong, not the code; corrected model → all pass |
| (b) branch operand read back from the compiled body | **2 bytes at `token+2`**; `0BRANCH@05ce` carries `05d2`, `0BRANCH@05e2 = 05ea`, `BRANCH@05e6 = 05ea`; every operand of B0–B4 (including 3-level nesting and a backward `BEGIN…UNTIL` self-branch) lands on a token boundary |
| (c) `BLOCK` stack discipline | `sp` delta **0** in all cases: `BLOCK 0` → address 3584, `BLKERR 0`; `BLOCK -1` → named `ERR_RANGE`, `BLKERR -5`, **no request sent** (`blk_out = 0`); `BLOCK 15` → `-3` with the request left outstanding |
| (d) `SAVE` status | one cell; `0` on success with the server's own copy showing `blk0[9]=0x42`; failure → `-2` named `ERR_BUSY`, `sp` unchanged, dirty flag still set |
| (e) buffer/dictionary overlap assertion | fires by name: `ERR_BUFOVER(xfer): dict_here=3634 > block_buffer=3584`, status `-6`, fetch refused, server copy untouched |

Two reader errors are now guardrails in the probe: **a body token is an xt** (`cf = rd16(xt)`), and **a colon
word's first token is `xt+2`**. Result dir: `probe/results/P38-fix-block-words/`.

## E-046 — FIRST ON-CHIP EXECUTION: our interpreter ran on the ULP (probe P39, PASS)

`2 3 + 4 * .` interpreted **on the coprocessor** produced **`20`** on UART0 as the bytes `0x32 0x30`,
`errf = 0`, `sp = rsp = 0`, no trap.

| Item | Value |
| --- | --- |
| flashed ULP `.bin` | **5 876 B** (`.text` 4 306 + `.rodata` 277 + `.data` 1 288 + pad) of 7 856 |
| engine total | **5 594 B**, of which **1 280 B is the baked prelude dictionary** ⇒ **4 314 B of engine code+rodata** |
| `nm -S` | `mem` 1280, `tsk` 420, `vm_live` 136, `tib` 128; **zero** `frm`/`ptab`/`blk` symbols |
| output bytes | `P39 OUT len=2 word=0x00003032` → `"20  "` |
| `wake_count` | **0 → 60** in a 400 ms window at period 1 000 ticks (`ulp_set_wakeup_period(0, 6460)` µs) |
| `rdcycle` at wake start | **187** (P05's 81 was an asm entry; the C prologue is included here) |
| failure modes | trap **disproved** (`RTC_CNTL_INT_RAW=0`, `cocpu_ctrl=0x0B4FC811`), never-ran **disproved**, wrong-answer **disproved** |

**New baseline: 4 314 B of engine** at 16-bit tokens, paging removed, no blocks.

**One thing does not fit, and it is instructive:** compiling the prelude **on the chip** needs **14 874 B**
against 7 856. Of that, **4 336 B is a second copy of the 62-body dispatch switch** — because `interpret()` is
`static`, GCC inlined `run()`/`vm_enter()` into `main()` while keeping the original copy in `interpret()`. The
remainder is the prelude's source text held in `.rodata` alongside the dictionary.

So: **a baked prelude runs; a boot-time-compiled prelude does not fit yet.** The fix is not less prelude — it is
(a) one dispatch switch, not two, and (b) streaming the source from flash instead of `.rodata`. Result dir:
`probe/results/P39-first-chip-run/`.

## E-047 — A live Forth REPL on the ULP (probe/repl)

The HP core is a byte pump between UART0 and two RTC-memory rings; the interpreter, the echo and the
prompt are all on the coprocessor. Verified on the board with `probe/repl/repl`:

| Sent | Received |
| --- | --- |
| (boot) | `ulp forth` + ` ok` — **printed by the ULP**, not the HP |
| `2 3 + .` | `5 ok` |
| `1 2 3 + + .` | `6 ok` |
| `: SQ DUP * ;` | ` ok` |
| `7 SQ .` | **`49 ok`** — a word defined at runtime, executed by the token interpreter |
| `BOGUS` | `BOGUS?` (the engine names the word; one message, not two) |

Image **6 120 B** of 7 856, engine + baked prelude (`MEMSZ` 1 280). Rings: 128 B command, 256 B output,
32 bytes drained per wake at a 1 000-tick period. Not present yet: blocks (`BLOCK`/`SAVE`), tasks.
Result dir: `probe/repl/` (an image, not a probe: the notes live here).

## E-048 — No Forth executes on the main cores (static, 6/6)

`probe/repl/tools/assert_ulp_only.py`, run against the shipping build:

```
HP  executable: p39_first_chip_run.elf
embedded ULP blob: file offsets 0x9f51..0xb72d (6108 B)
ULP dictionary `mem`: 1280 B
dictionary payload: 1 occurrence(s), all inside the embedded blob
HP evaluator symbols: none of interpret, vm_enter, do_colon, vm_run, run_line, repl_drain
ULP evaluator: main = 2956 B (inlined dispatch loop)
HP bridge source: no line discipline, no evaluator, no echo
PASS — no Forth executes on the ESP32's main cores
```

## E-049 — Counterfactual: with the coprocessor stubbed, the console is silent

Stub image (`REPL_ULP_STUB=1`, `src/ulp_stub.c`): identical bridge, ULP `main` bumps a counter and returns.
ULP image **132 B**.

```
boot: ulp forth bridge, 132 B image
type Forth at the prompt; 'picocom -b 115200 /dev/ttyACM1'
ulp woke 76 times              <- coprocessor alive, 76 x 6.5 ms = 0.5 s
>>> "2 3 + ." -> b''           <- zero bytes: no echo, no prompt, no error, no answer
```

Restored real image, same bridge, same terminal:

```
ulp woke 76 times
>>> "2 3 + ." -> b'2 3 + .\n5 ok\n'
```

Echo, prompt and interpretation are therefore ULP-only. The wake counter is what makes the silence mean
something: it rules out "the coprocessor never started".

## E-050 — The technical reference manual, adopted into the cache

`tools/fetch.py get https://www.espressif.com/sites/default/files/documentation/esp32-s3_technical_reference_manual_en.pdf`
→ `cache/objects/b944c82a0e7e8532038586f1b2cd12ce/v0001.bin`, **15 215 232 B**, `application/pdf`, sha256
`4484bf8a69035ec42a731c58c64ada6fbd1f1618c5559409f134d9ea083f444f`, journaled `store` event.
Text extracted (PyMuPDF; `pdftotext` is blocked by its firejail profile, which cannot see the repo) to
`cache/derived/esp32s3-trm.txt`: **1 531 pages**, 2.29 M characters.

Content check, so the document's limits are known before anyone counts on it:
* §2 "ULP Coprocessor (ULP-FSM, ULP-RISC-V)" begins p. 304; §2.4 sleep/wake workflow p. 307.
* 520 occurrences of "cycle", 0 of them a per-instruction cost for the RISC-V coprocessor — §1.7 is Xtensa,
  §2.5.2.1 is the FSM. Timing still comes from `rdcycle` (P05, P14).
* 0 hits for `RTC_CNTL_SLP_WAKEUP_CAUSE`, so P06's "wake cause reads 0" stays a measured fact.

## E-051 — ISA and ABI documents cached; the ULP's arithmetic priced by the manual and the compiler

| Document | object | size | pages | sha256 |
|---|---|---|---|---|
| ESP32-S3 TRM v1.8 | `b944c82a…` | 15 215 232 B | 1 531 | `4484bf8a69035ec4…` |
| RISC-V unprivileged ISA, ratified 20191213 | `b15c7807…` | 1 021 610 B | 238 | `f392624cc815cd3f…` |
| RISC-V ELF psABI 1.0 | `652cde45…` | 273 939 B | 56 | `a8d06bdcaa82a6a4…` |

Build contract, from `build/esp-idf/main/ulp_main/compile_commands.json` (not from prose):
`-Os -march=rv32imc_zicsr_zifencei -mdiv -ffunction-sections -fdata-sections`; ABI ILP32 soft-float.
TRM §2.6.1: "Support RV32IMC instruction set", 32 GPRs, 32-bit multiplier and divider.

TRM §2.6.2 Table 2.6-1, instruction efficiency: `MUL` 34, `MULH`/`MULHU`/`MULHSU` 66,
`DIV`/`DIVU`/`REM`/`REMU` 34 cycles.

Codegen check (`probe/isa/codegen.c`, same flags, `objdump -d`):
```
<m_mul>:  mul a0,a0,a1 ; ret      <- one instruction, no stack frame
<m_div>:  div a0,a0,a1 ; ret
<m_mod>:  rem a0,a0,a1 ; ret
<ret> assembles to 2-byte c.jr    <- RVC compressed encodings live
```

Hot-path check (`probe/isa/ulp_main.dis`, `main` = 1 038 instructions): 0 multiply in the dispatch path — all 59
index scalings are `slli`. The image's only `mul`/`div`/`rem` (3/1/2) are in number printing and parsing.

## E-052 — What the shipping image has already paid for, and what `--gc-sections` deleted

Symbols in `probe/repl/build/esp-idf/main/ulp_main/ulp_main.elf` (6 120 B image, 7 258 B of pool):

```
tsk              420 B   b   <- 3 task records, allocated, inside the 7 258 B
vm_switch        102 B   t   <- linked, called from vm_task_leave and from main's pause path
vm_task_leave    120 B   t   <- linked: the retire path is live
vm_task_init     ---         <- absent: 0 callers, eliminated
vm_next_ready    ---         <- absent
vm_run_tasks     ---         <- absent
```

Forcing every static function to be emitted (`-fkeep-static-functions`, same flags) recovers the price list the
linker deleted:

| Function | Size | | Function | Size |
|---|---|---|---|---|
| `vm_enter` (paged path) | **2 520 B** | | `number` | 176 B |
| `drain_cmd` | 302 B | | `interpret` | 252 B |
| `mkhdr_pad` | 204 B | | `run_line` | 154 B |
| `vm_run_tasks` | **80 B** | | `vm_task_init` | **72 B** |
| `vm_next_ready` | **54 B** | | `run` | 24 B |

Net `.text` difference: **4 948 → 5 440 B (+492 B)** — the functions exist either way, inlined into `main` (2 956 B)
or emitted; the flag changes the organisation and exposes the sizes.

### The `lhu` variant, measured rather than assumed

`rd16(a) { return rd8(a) | rd16(a+1) << 8; }` → `a + 1u < MEMSZ ? *(volatile u16 *)(mem + a) : 0u`
(no masking, no byte-pair fallback: a misaligned access must trap, per the guardrail in the variant).

* `.text`: **4 948 → 4 936 B** (−12 B). `rd16` section: 54 → 36 B.
* `rd16` is **out of line**, not inlined: 42 B, **11 call sites**. `rd32` 34 B / 18 sites, `rd8` 30 B / 12 sites.
* `NEXT` is 480 cycles for ~20 instructions => **~24 cycles per instruction**, i.e. RTC RAM latency dominates.
  Cutting one load is therefore a **latency** question, not an instruction-count question — which is exactly why the
  earlier framing of this as "the single biggest lever" was overstated, and why P42 must run on the chip.

Cycle effect of both variants is **not yet measured**; that is P42.

## E-053 — P42: the halfword token fetch is 35.2 % faster, measured on the chip

Bench image (`-DP42_BENCH -DP42_COUNT -DP42_ONLY`), workload `0 1+ 1+ ... DROP` (colon words, so tokens are
actually fetched), 32 reps, minimum reported, two line lengths so per-call overhead cancels. Harness validated
`err = 0`, `sp = 0`, `rsp = 0`, `ti == tl` before timing. Reproduced exactly across reboots.

| Image | short (81 disp) | long (161 disp) | **cycles/dispatch** | intercept |
|---|---|---|---|---|
| `rd16` = `rd8(a) \| rd8(a+1) << 8` | 193 928 | 334 548 | **1 757.75** | 51 550 |
| `rd16` = one `lhu` | 122 804 | 213 944 | **1 139.25** | 30 525 |

**−618.5 cycles/dispatch (−35.2 %).** Reason: 1 758 cycles per dispatch is ~24 cycles per instruction, and the old
`rd16` made two `rd8()` calls, each a `jal` + bounds check + load + `ret`.

Adopted into `src/uforth.c`. Shipping image **6 112 B**, pool **7 264 B** of 7 856 B (**+6 B**), verified on the
board: `2 3 + .` → `5 ok`; `: SQ DUP * ;` + `7 SQ .` → `49 ok`; `: CUBE DUP DUP * * ;` + `3 CUBE .` → `27 ok`;
`BOGUS` → `BOGUS?`; `21 D2 .` → `42 ok`.

Harness defects found on the way (all recorded, all fixed): `BEGIN`/`UNTIL` are compile-only; primitives never
fetch a token; calling `interpret()` from inside `drain_cmd()` breaks the machine; printing through the engine's
`.` pulls a second 2 586 B interpreter copy and overflows the pool.

## E-054 — Levers measured: app space is 144 B, and it can be 1 316 B

Method: `probe/lev/ulpmeasure.sh <src> <out.elf>` — compile one candidate source with the recorded ULP flags,
relink against the prebuilt IDF ULP core objects, read `riscv32-esp-elf-size`. Baseline reproduction came first and
matched the shipping figure exactly.

`V_HERE` at boot, decoded from `src/image.h` (1 136 initialised bytes): **1 136 B**; `V_LATEST` 1 000. App space is
`MEMSZ 1280 − 1136` = **144 B**, not the 620 B in the docs — that 620 required `MEMSZ` 2 196 and therefore a pool of
8 180 B, which never fit.

| config | text | rodata | data | bss | pool | spare | app space |
|---|---|---|---|---|---|---|---|
| baseline | 4 508 | 316 | 1 288 | 1 152 | 7 264 | 592 | 144 B |
| `MEMSZ` 1 400 | 4 508 | 316 | 1 408 | 1 152 | 7 384 | 472 | 264 B |
| `MEMSZ` 1 640 | 4 508 | 316 | 1 648 | 1 152 | 7 624 | 232 | 504 B |
| `MEMSZ` 1 760 | 4 508 | 316 | 1 768 | 1 152 | 7 744 | 112 | 624 B |
| `MEMSZ` 1 872 | 4 508 | 316 | 1 880 | 1 152 | **7 856** | 0 | **736 B** |
| `MEMSZ` 1 880 | 4 508 | 316 | 1 888 | 1 152 | 7 864 | **−8** | overflow, link still succeeds |
| + rings 64/128/96 | 4 504 | 316 | 1 880 | **928** | 7 628 | 228 | 964 B |
| + `NTSK` 3→1 | **4 430** | 316 | 1 880 | **872** | 7 498 | 358 | 1 094 B |
| combined, `MEMSZ` 2 452 | 4 432 | 316 | 2 460 | 648 | **7 856** | 0 | **1 316 B** |

Every +120 `MEMSZ` moved `.data` by exactly +120. `MEMSZ` 1 880 overflows without the linker complaining.

Process note: the first sweep reported identical rows for every value because the `sed` pattern did not match the
source (5 spaces vs 6). **A sweep whose rows are all identical means the edit did not apply**; the loop now echoes
the effective value it measured.

## E-055 — R4 on the chip: two and three Forth tasks interleave, driven from the REPL

`SPAWN` parses a name, resolves its xt and takes a task slot; tasks are stepped once per wake from `main()` after
the drain. Bodies use `PAUSE` so the switch is observable:

```
: TA 1 . PAUSE 2 . ;
: TB 3 . PAUSE 4 . ;
SPAWN TA SPAWN TB            ->  ok / 1324        (1 3 2 4: each task yields mid-body)
SPAWN TA SPAWN TB SPAWN TA   ->  ok / 131242      (three tasks, three slots)
2 3 + .                      ->  5 ok             (the REPL survives)
5 6 SPAWN TA                 ->   ok / tasks need an empty stack   (exactly once, then retired)
. .                          ->  65 ok
42 .                         ->  42 ok
```

Image **6 880 B**, pool **7 842 / 7 856** (14 spare), `MEMSZ` 1 500, `V_HERE` 1 146 → **app space 354 B**.

Cost of R4, measured: `.text` 4 518 → 5 014 (**+496 B**: `vm_spawn_name`, `vm_task_init`, `vm_next_ready`,
`vm_run_tasks`, the case body, the step in `main`), plus 10 B of dictionary for the `SPAWN` header. The 420 B of task
records were already allocated.

Also in this run: `vm_task_leave` no longer calls `pl_halt(0)` when the last task retires — that was written when
tasks were the only driver and it killed the console. It returns to C with `cur = -1`.

## E-056 — The ring sizes were duplicated across the two cores, and the mismatch corrupted the console

When the ULP rings shrank to `CMD_SIZE 64` / `OUT_SIZE 128`, `main/repl_main.c` still held **128 / 256**. The host
therefore masked its write index with 127 and wrote past the end of `repl_cmd[]` **into `repl_out[]`**, and read the
output ring with mask 255. Symptom: the REPL replayed stale characters — `3 CUBE .H`, `.HERE?`, and lines arriving
several commands late.

* With the mismatch: `3 CUBE .` → `3 CUBE .H`; `BOGUS` → `ERE .\n.HERE?`; 3 of 9 checks failed.
* After matching the constants and exporting `repl_cmd_bytes`/`repl_out_bytes` from the ULP with a boot-time assert
  on the host: **9 of 9 pass**, including `3 CUBE .` → `27 ok` and `BOGUS` → `BOGUS?`.

Two sub-lessons: the exported size symbols were deleted by `--gc-sections` (nothing on the ULP read them), which
broke the host build with `'ulp_repl_cmd_bytes' undeclared` — they are now used by a real self-check; and the
**IDF build does not report pool usage**, so an over-budget image (7 902 B) built, flashed and ran — `ulpmeasure.sh`
caught it, the build did not.

## E-057 — `rd32` as a single `lw`: costs bytes, and would trap. The `rd16`/`rd32` asymmetry, explained

Three-way measurement of the shipping tree (post-R4) by the parent, plus an independent lane audit:

| tree | text | rodata | data | bss | pool | spare |
|---|---|---|---|---|---|---|
| baseline | 5 014 | 348 | 1 516 | 964 | **7 842** | 14 |
| `rd32` = one `lw` | 5 038 | 348 | 1 516 | 964 | **7 866** | **−10** |

**+24 B, not a saving.** (The subagent measured **+38 B** on the pre-R4 tree: same sign, different magnitude.) The
34 B out-of-line `rd32` disappears and all 18 call sites inline, so the body is paid 18 times instead of once — the
opposite of `rd16`, where losing a *call* was the win.

**And it would trap.** `P_LIT` is `PUSH(rd32_paged(ip)); ip += 4;` and `clit()` writes the cell as two 2-byte halves
(`cw(v); cw(v >> 16)`) with no alignment step, so a literal's value sits at `token+2` — **2 mod 4 whenever the `X_LIT`
token is 4-aligned**. `lw` requires 4; `lhu` requires 2. That is why `rd16` → `lhu` was safe (E-053) and why `rd32`
must stay byte-wise. The independent lane walked the shipped `mem[]` and found 8 of 18 real literal sites at
`≡ 2 (mod 4)`, naming `HERE`, `IMMEDIATE`×2, `IF`, `UNTIL`, `1-`, `WHILE`, `REPEAT`; the trap would fire on `HERE`.

Also established by the same audit: header links are written `wr16` and read `rd16` — a **2-alignment** contract, not
4 — and 37 of 81 headers are 4-aligned, so a 4-byte link read would be wrong today regardless of `lw`.

## E-058 — Blocks are 600–1 090 B out of reach, and the arithmetic is now explicit

Parent-verified constants: pool = `MEMSZ + 6 342` (measured: 1 500 → 7 842 ✓; composition 5 014 text + 352 rodata
+ 960 bss + 16 = 6 342 with `.data` = `MEMSZ + 16`).

* `blk_place_ok` requires `V_HERE ≤ MEMSZ − 512`. With the block words compiled in, `V_HERE = 1 146 + 456 = 1 602`,
  so **`MEMSZ` ≥ 2 114`**, giving pool **8 456 — 600 B over** 7 856.
* With ≥200 B of app space, `MEMSZ` ≥ 2 314 → pool 8 656, **800 B over**.
* Holding today's 354 B of app space: `MEMSZ` 2 604 → **1 090 B over**.

Available levers, measured: rings **already taken** (224 B, 0 left), `MEMSZ` slack **spent** (ceiling 1 514 vs 1 500),
`NTSK` 3→1 **358 B** (deletes 2 of the 3 task slots R4 demonstrated), full R4 removal **916 B** (deletes R4),
C-stack 320 B **forbidden**. Keeping R4: **0 B available.**

Verdict: blocks need a different shape, not a bigger sweep — a smaller buffer, a paged reader, or storage that does
not sit inside `MEMSZ`.

## E-059 — Blocks as C primitives: saves 490 B of dictionary, still 432 B short

Three measurements, all parent-run.

**(a) The Forth layer's composition** (host image dump, `-DP33_BLOCK`):
`prelude+line` 1 158 B → `+5 CONSTANT +3 CREATE` **1 304** → `+ full blocks.fs` **1 688**. So the layer is
**530 B**, not the 456 B on record: **146 B of constants/variables (8 dictionary entries) + 384 B of code and error
strings**.

**(b) Blocks as C primitives** (`BLOCK`/`UPDATE`/`SAVE` in C, `.bss` cells, no constants, no `RAISE`), object sections:

| build | `.text` | `.rodata` | `.bss` added |
|---|---|---|---|
| baseline | 5 694 | — | — |
| + block plumbing (`blk_xfer` 186, `blk_sum` 56, `mailbox` 216) | 5 694 | — | 216 |
| + 3 C primitives (`vm_enter` +290, `blk_say` 34) + `blkvars` 12 | 6 311 | +16 | +12 |

**(c) The trade**

| | dictionary | text+rodata+bss | pool |
|---|---|---|---|
| Forth layer | **530** | plumbing only (~500) | — |
| C primitives | **40** (3 headers) | plumbing **+350** | — |
| **delta** | **−490** | **+350** | **≈ −140 to −154 saved** |

**Verdict: a real but small win.** Blocks as C primitives would take the image to **8 288 B** against 7 856 —
**432 B over**, versus **922 B over** for the Forth layer. The lever works; it does not close the gap.

**Two findings that change the block budget:**

1. **The plumbing was never counted.** `blk_xfer` (186 B) + `blk_sum` (56 B) + the mailbox (**216 B**, a `u32[54]`
   of which the protocol uses four words) ≈ **500 B** must be added to *any* block figure. "968 B" was
   dictionary-plus-buffer only; the honest number is **~1 300–1 500 B**.
2. **The layer's cost is mostly not code.** 146 B of it is eight dictionary entries — five `CONSTANT`s and three
   `CREATE`d cells — that exist only so Forth can say `BLKERR @`. That is what the C port actually removes.

Next lever if blocks matter: the `mailbox[54]` (216 B) is sized for P04's full status block and the block protocol
uses four words; a purpose-built 16 B mailbox would return ~200 B, which together with the C port would put blocks
within ~230 B.

## E-060 — P45 (where a dispatch's cycles go): **INVALID**, no number obtained

Two runs, both self-invalidating. What they did establish is a list of harness defects, and one *preliminary*
observation that is explicitly **not** a measurement.

**Harness defects, in the order they appeared:**

1. **Line longer than `TIBSZ`.** The `1 1 + 1 + …` workload at 40 groups filled 166 bytes into a 128-byte `tib`,
   overwriting the ring indices. Reported `1 020 231 cycles` for `21 dispatches` and `err=4`.
2. **Stack-underflowing workload.** `1 +` with one operand wraps `sp`; the valid-check fired and refused.
3. **Dispatch counter not compiled in** in the derived tree (`P42_COUNT` gate lost in the copy), so every
   `dispatches` field read 0 and the slope guard reported `err=4`.
4. **Four-point logic half-wired:** the 8-group points returned 0 cycles, so only the 4-group points existed, with
   too much fixed overhead to separate per-word from per-dispatch cost. Solving the two equations gave a *negative*
   dispatch cost, which is how the inconsistency announced itself.

**Preliminary observation, labelled as such:** the 4-group literal line cost **113 194 cycles for 5 parsed words** —
on the order of **20 000+ cycles per interpreted word**, against ~1 139 cycles for a dispatched body token (E-053).
If that survives a correct measurement, the dominant cost of *typing* at this REPL is parse + `find()` (a linear
scan of 81 headers), not dispatch — which would mean hand-written assembly for the dispatch loop optimises the path
the machine already takes fastest.

**Not established:** the prologue/epilogue share of a dispatch. The disassembly still says 24 of ~47 instructions
(vm_enter: `addi sp,sp,-64`, then ten `sw`/`lw` of s0–s10), but that is a static reading, not a cycle measurement.

## E-061 — The cost of typing was in the name lookup: 17.3x faster literals, 4.7x faster lines

P46 measured the split on the *validated* P42 harness (one validation pass, hex output, `err = 0`). The
two-point model was deliberately over-determined and returned a **negative** dispatch cost, which is the
arithmetic announcing that per-word cost is not uniform — the finding, not a failure.

Two workloads, two lengths each (`L(g)` = g literals, zero dispatches; `P(g)` = "1 1 " + g × "+ 1 "):

| | parsed literal word | group (2 words + 1 dispatch) |
|---|---|---|
| before | **28 155 cycles** | **48 344** |
| after the fix | **1 623** (−17.3×) | **10 305** (−4.7×) |

**Where the 28 155 cycles were:** `find()` walks the header chain (81 entries) and, in the old order,
`interpret()` called `find()` *first* and `number()` only after it failed — so **every literal in the source paid
a failed full scan**. And each header iteration made **two calls** (`rd16` for the link, `rd8` for the length); a
call costs ~240 cycles on this core, so 81 × 2 × 240 ≈ 39 000 — matching the measurement.

**Two changes, both C, both small:**

1. `interpret()` tries `number()` first when the token starts with a digit or `-` (with `n > 1`, so the `-` word
   still resolves as a word).
2. `find()` reads the link and the length byte **directly** instead of through `rd16()`/`rd8()` — no alignment
   contract needed, and no call per header.

Verified on the board after adoption: `2 3 + .` → `5 ok`, `-5 .` → `-5 ok`, `9 4 - .` → `5 ok`,
`: SQ DUP * ;` → ` ok`, `7 SQ .` → `49 ok`, `: CUBE DUP DUP * * ;`/`3 CUBE .` → `27 ok`, `BOGUS` → `BOGUS?`,
`123456 .` → `123456 ok`, `HERE .` → 1 180 after two definitions, and **R4 still prints `1324`**.

**Cost:** `.text` 5 014 → 5 156 (+142), so `MEMSZ` 1 560 → 1 372 to stay inside the pool. **App space 354 → 226 B**
and pool exactly 7 856 (C-stack reserve 336 B, above P21's 244 B floor).

**Two process findings from the same run.** `idf.py build` still does not report pool usage, so the first attempt
flashed **7 984 B** — 128 B over — and the ULP C stack overflowed into `.bss`, which presented as *corrupted
interpreter state* (a bare `?`, definitions that vanished), not as a build failure. `probe/repl/flash_safe.sh` now
measures and refuses before flashing; its first version double-counted the `dec` column and refused a legal image,
which at least proved the gate fires.

## E-062 — Memory victory: 144 B → 558 B of app space, R4 intact, pool 7 852

**P47: kill the libgcc calls.** `vm_switch` made two `memcpy` calls (the 136 B VM struct copies) and `vm_enter` a
`memset`; together 127 instructions, 7 % of text. Enabling the hand-written word copy already present in `uforth.c`:
**text 5 156 → 4 800 (−356 B)** — the largest byte win available without deleting a requirement. Spent on `MEMSZ`
(1 372 → 1 704): **app space 226 → 558 B**.

**A latent bug in that path, found by the third task.** `vm_copy` unrolled four words per iteration with the loop
bound `sizeof(VM)/4` — but `sizeof(VM)` is 136 B = **34 words, not a multiple of 4**, so the last iteration copied
4 words with 2 remaining: an **8-byte overrun into the adjacent task record**. Two tasks worked (`1324`); **three
tasks hung the machine dead** and every later line returned nothing. Fixed to copy whole words then the tail
(+20 B of text, `MEMSZ` 1 704). Verified: **3 tasks print `131242`** and the machine answers after.

Final state, all verified on the board in one session:

```
2 3 + .                     -> 5 ok
: SQ DUP * ;  7 SQ .        -> 49 ok
: CUBE DUP DUP * * ;  3 CUBE . -> 27 ok
BOGUS                       -> BOGUS?
123456 .                    -> 123456 ok
SPAWN TA SPAWN TB           -> ok / 1324
SPAWN TA SPAWN TB SPAWN TA  -> ok / 131242
2 3 + .  (after tasks)      -> 5 ok
HERE .                      -> 1236 after two definitions
```

| | session start | now |
|---|---|---|
| app space | **144 B** | **558 B** (3.9×) |
| pool | 7 264 (592 spare) | **7 852 / 7 856** |
| dispatch (compiled code) | 1 757.75 cyc | **1 139.25 cyc** (−35 %) |
| typed literal | ~28 000 cyc | **1 623 cyc** (−17.3×) |
| requirements | REPL | REPL **+ R4 tasks** |

## E-063 — P48: hand-written asm for the dispatch core, priced before committing

**Merge first (the precondition).** The victories were unprotected: `probe/uforth/host_test.c` tests the *prototype*,
not the shipping engine. Added `probe/repl/tests/suite.fs` + `run.sh` — 26 assertions against `src/uforth.c` built
for the host, diffed against a golden output whose every value was hand-checked
(`5 4 42 6 15 -5 -2 123456 49 10 10 49 27 42 1 -1 0 0 7 0 1276 -1`). **PASS.**

**Then the pricing.** GCC's encoding is already near the RVC floor — `vm_enter` is 848 instructions in **2 392 B =
2.82 B/instruction** — so assembly cannot win on encoding. It can only win by executing *fewer instructions*, which
means changing the stack convention: the C engine addresses the stack as `ds[(sp-1) & (SD-1)]`, costing
`andi + addi + slli + add + lw` per operand; a register holding a **pointer to TOS** makes it `lw t0, 0(s2)`, and
push/pop become `addi s2, s2, ±4`. RISC-V has no scaled addressing, so no compiler discovers this.

Measured, same toolchain and flags:

| | bytes per primitive body |
|---|---|
| GCC, extracted from the shipping `vm_enter` (64 bodies, 1 890 B) | **29.5** (median 28, range 8–58) |
| hand-written, TOS-pointer convention (`proto.S`, 6 primitives, 90 B) | **15.0** (includes a `ret` the inline cases do not pay) |

**Projection:** 8–14 B saved per body × 64 bodies = **510–930 B**. The blocks gap is **~850 B**. So the rewrite
plausibly closes the gap, but not with certainty — and the prototype covered the *simple* primitives, whose C
bodies are already among the cheapest, so the real average saving is more likely at the low end of that range.

**What the rewrite must not break:** the resumability contract (P27) — the VM is memory and a switch is a 136 B
copied struct. A register-resident TOS pointer must therefore be spilled to the record on every switch, i.e. `s2`
and the `mem` base become part of the save set. That is the whole risk of the change, and it is exactly what
`tests/suite.fs` cannot cover — the suite is host-side and R4 is board-side, so the rewrite needs both.

## E-064 — "Drop GCC and gain space": measured, and the answer is no

Three checks on the shipping source.

1. **No libgcc helpers remain.** `nm` finds no `memcpy`, `memset`, `__mulsi3`, `__divsi3`, `__modsi3`, `__udiv*`. P47's
   `P30_HANDCOPY` already removed the last of them, so there is nothing to reclaim here.
2. **Compiler flags are exhausted.** Same source, three optimisation levels, `.text` totals:
   `-Os` **5 550 B**, `-Oz` **5 550 B** (identical), `-O2` **7 900 B**. `-Os` is already the optimum for this code.
3. **Encoding is at the RISC-V floor.** `vm_enter` is 848 instructions in 2 392 B = **2.82 B/instruction**, i.e. the
   overwhelming majority of instructions are already 16-bit compressed forms.

So deleting the compiler buys **zero bytes**. What buys bytes is the *convention*: GCC cannot express
"a register holds a pointer to TOS", so every stack access pays `andi + addi + slli + add + lw`. That is P48's
measured **29.5 B/body → 15.0 B/body**, worth **510–930 B**, and it lives entirely inside `vm_enter` — which is
**2 392 B, exactly 50 % of all text** (the other 26 functions are the other 2 424 B).

**An all-assembly engine would add little and cost a lot:** the remaining 50 % is logic (parse, find, number, headers,
error reporting, the REPL), where asm saves ~10 % at best (~240 B) while removing the only debugger-friendly form and
— decisively — breaking the PC-side image generator, which bakes `image.h` by *compiling `uforth.c` on the host and
running it*. Losing the generator loses the vocabulary.

## E-065 — P49: coverage of the code the linker *keeps*

`gc-sections` already deletes what nothing references, so the remaining question is what is **referenced but never
executed**. Instrumented the host build (`-DP49_COVER`): the dispatch loop records each primitive id it executes, and
`find()` records each header it matches. The report prints **names read from the headers themselves**, not from a
parallel list.

Workload: prelude compilation + `tests/suite.fs` (26 assertions).

```
P49 never-dispatched: WAKE MS ADC@ GPIO! GPIO@ (.") ." LITERAL ' CONSTANT CREATE C, , TYPE KEY? KEY
                      U< RSHIFT LSHIFT INVERT XOR AND U/MOD W@ ! ROT OVER EXECUTE UNLOOP J I (+LOOP) (LOOP) (DO)
                      (count 34)
```

**34 of 65 primitives were never dispatched** by that workload. They are perfectly reachable — the linker keeps every
primitive in the table — but nothing in this workload runs them.

**Price of the optional set**, measured by building with `P31_SUBSET` (which drops the gated primitives):

| build | text | rodata | pool |
|---|---|---|---|
| full set (shipping) | 4 820 | 348 | 7 852 |
| `P31_SUBSET` | **2 314** | 80 | 5 054 |

So the non-essential primitives are worth **~2 500 B of text**, and the coverage list names which ones this machine
actually uses.

**Two findings about the method itself.** (1) The first report was wrong: pairing a bit index with a name list parsed
out of the `X()` macro files reported `DUP` as never-dispatched, because the list and the enum disagreed by two
entries. Reading the name from the header makes that impossible. (2) A local variable named `w` in the dump collided
with the engine's `#define w (V->W)` and produced an error pointing at the macro's *definition* — the exact trap the
source's own guardrail warns about.

## E-066 — P50 groundwork: the asm dispatch core, contract and guardrails (implementation pending)

**Done and building.** `src/pids.h` generated from the enum order, plus **13 `_Static_assert`s** in `uforth.c` tying
every id the assembler will use to the real enum, and asserting the two layout facts the asm hard-codes
(`SD == 16`, `sizeof(VM) == 136`). Text unchanged at 4 820 B; suite green.

**The asserts caught two of my own mistakes before any asm existed** — first the macro names were guessed
(`P_PLUS` instead of `P_ADD`), then the three `DO*` entries that the enum declares *before* the X list were
forgotten. Both failed the build instead of producing a jump table that silently dispatches the wrong case. That is
F-98 (one owner per ordering) made mechanical.

**The loop contract, read out of the source rather than assumed:**

```
cf = rd16(mem + w)            the token AT w — a primitive id, or a colon body's DOCOL
switch (cf) { ... }           a case may push/pop, or set ip (DOCOL: RPUSH(ip); ip = w + 2)
if (!ip) return               nothing left in this machine -> back to C
w = rd16(mem + ip); ip += 2   fetch the next token
```

VM layout the assembler must match: `DS 0..63`, `RS 64..127`, `SP 128`, `RSP 129`, `W 130..131`, `IP 132..133`,
`sizeof 136`. Stack addressing is `ds[(sp - 1) & 15]`, so **SD must be 16** — now asserted.

**Correction to the projection in E-063.** The 15.0 B/primitive prototype stated "s2 = pointer to TOS, VALID for the
prototype" — i.e. it omitted the 16-cell **wrap check**. The real dispatcher must either mask per access (which is
what C already does, and gives no win) or allow one cell of transient overshoot and re-derive the pointer once per
dispatch. With that, the realistic figure is **~18–22 B per body**, so the projection drops from 510–930 B to
**≈ 400–700 B**. Still the blocks lever, but the low end of it.

**Not yet done, and deliberately:** the asm loop itself, and inline cases for the first primitives. Two reasons it
was not rushed into the tree: the integration requires extracting the switch into a `vm_case(cf)` fallback, and —
decisively — **RISC-V assembly cannot be exercised on the host**, so any asm change is validated only by flashing the
board and re-running the typed suite plus the 2- and 3-task cases. Half-built asm in the tree at the end of a session
is worse than none.

## E-067 — The countdown metric, and the two blockers asm hit immediately

**Metric in place.** `probe/repl/countdown.sh`, printed by `tests/run.sh` on every green run, so progress is
measured in the same units every time:

```
blocks countdown: 800 B to go  [pool 7852/7856]
  need: dict 40 + buffer 512 + block code 810 = 1362 B
  have: app 558 + pool spare 4 = 562 B
```

The target is a fixed configuration (block words as C primitives), and the script's constants are labelled as
measurements with their source (E-059). Note what the ledger says about *where* the gap is: the target `MEMSZ`
(V_HERE + 40 + 512 = 1 698) is **below** the current 1 704 — so the entire 800 B is the block layer's **code**, not
its dictionary. Text reductions (ascii: asm) add directly to "have".

**Blocker 1 — P31's gates bind name and body together.** `p31_prims.inc` and `p31_cases.inc` both test
`!defined(P31_SUBSET) || defined(P_HAVE_DUP)`: one macro controls the dictionary entry *and* the C case body. There is
no way to express "keep the name, drop the C body" — which is exactly what an asm body needs. Workaround: register the
asm-handled primitives manually in `boot_init` with their ids (assert-guarded), and let `P31_SUBSET` drop their C cases.

**Blocker 2 — five case bodies assume the loop.** `p31_cases.inc` contains **5** `continue;`/`return;` statements
(EXIT and the DO/LOOP family), so the switch cannot be extracted into a `vm_case(cf)` fallback without editing the
generated `.inc` — which the project's own guardrail forbids, because P30/P31 kept that file verbatim so variant diffs
stay meaningful. Consequence: those primitives must stay in C, and asm handles only bodies with no loop control flow
(DUP, DROP, SWAP, OVER, ROT, +, -, 0= are all clean).

**Safety net added.** The dispatch switch now has `default: err(); break;`. With cases moved to asm, a token whose
case was removed would otherwise fall through and continue with unchanged stacks — the worst failure mode here,
because every symptom would look like a Forth error rather than a missing dispatcher entry. Suite green after the
change.

## E-068 — P50: the asm dispatch loop compiles, and the projection improves to ~719 B

First working assembly for the dispatch core: `probe/lev/p50asm/dispatch.S`, a loop that keeps **a pointer to TOS
in `s2`** across dispatches (the convention GCC cannot express) and handles `DUP`, `DROP`, `+`, `0=` inline,
publishing state and returning the token to C for everything else.

**Measured**: `.text` = **278 B** for the loop plus those four bodies.

Breaking that down by inspection of the listing (`DUP` push macro ≈ 10 instructions, `DROP` ≈ 6, `+` ≈ 12, `0=` ≈ 5,
all RVC-compressed at ~2.82 B/instruction):

| | loop | per body | 64 bodies total |
|---|---|---|---|
| GCC (extracted from the shipping `vm_enter`) | ~502 B | 29.5 B | **2 392 B** |
| hand-written asm | **~185 B** | **23.2 B** | **~1 673 B** |

**Projected saving ≈ 719 B** — against a countdown of 800. That covers **90 %** of the blocks gap, and it is the
upper end of E-066's corrected 400–700 estimate because the *loop* turned out to be the cheaper half to rewrite:
C's loop carries the bounds check, the checkpoint read, the jump table and the `!ip` path in ~502 B.

**Why the wrap check did not eat the win.** Each push/pop re-derives `s2` when `s3 & 15` crosses the boundary
(~4 B per body). The 15 B/body prototype omitted that entirely; including it still lands at 23.2 B versus GCC's
29.5 B, so the pointer convention survives the correction.

**What is deliberately not done:** porting the remaining 60 bodies, and integration. The loop's contract with C is
sketched (`0xffff` = machine finished → C runs the `!ip`/task-leave path; otherwise the returned token goes through
the C switch, whose `default: err()` now catches a missing case). Validation cannot happen on the host — RISC-V
assembly only runs on the chip — so the port must be followed by a board session running the typed suite plus
`1324` and `131242`.

**The honest risk:** 60 more bodies, several of which call C helpers (`mkhdr`, `number`, `find`, `blk_xfer`) and
therefore need a store-state / call / reload sequence (~30 B each), which is where the 23.2 B average will rise.
A realistic final figure is 1 700–2 000 B, i.e. a saving of **400–700 B** rather than a flat 719.

## E-069 — P50: the call-based integration is a measured LOSS; only replacing the loop pays

Wrote `p50_try(cf, &V, &mem)` — seven bodies (DUP, DROP, SWAP, OVER, +, -, 0=) behind an id-compare chain, designed
to be called from the C loop before the switch. Measured:

| component | bytes |
|---|---|
| `p50_try` total | **368** |
| prologue/epilogue (7 saves + 7 loads + frame + ret) | ~56 |
| seven `li`+`beq` id comparisons | ~40 |
| **seven bodies** | **272 (39 B each)** |

GCC's cost for the same seven primitives is **~84 B** — they are the *simplest* bodies in the engine, 8–12 B each in
the inlined switch. So the call-based shape is a **loss of ~188 B** before a single C case is removed.

**Why**, and it is not the bodies: a per-token call pays a frame, a seven-way compare chain and a return, for a body
of two or three instructions. The earlier in-loop measurement (278 B for the *loop* plus four bodies, no call and no
comparison chain, dispatch through a jump table) is the opposite shape and is the only one that can pay.

**Design consequence, recorded before spending more time:** the asm must **replace `vm_enter`'s loop**, not be called
from it. That means the asm owns the fetch, the jump table, the `!ip`/task-leave path and the fallback for the
primitives it does not implement — including the five that contain `continue`/`return` (E-067).

**Second measurement worth keeping:** in-loop, the wrap-checked `NOSADDR` sequence costs ~5 instructions
(`addi`, `andi`, `li`, `bne`, `addi`) for every two-operand body. That is what pushes bodies from the prototype's 15 B
to ~23 B, and it means the 719 B projection is an upper bound rather than an expectation.

## E-070 — P50 verdict: the asm dispatch core cannot pay for blocks. Measured, and it corrects my own estimate twice

Built the loop-replacement form as designed (`p50_loop` owns fetch, id-range dispatch, per-body wrap re-derivation and
the `w/ip` advance; C keeps the switch for everything else and owns `!ip`/task retirement). Measured:

| | bytes |
|---|---|
| `p50_loop`: loop + 7 bodies + 2 jump tables | **490** (466 text + 24 rodata) |
| the 7 C cases it could remove | ~84 (they are the cheapest bodies in the engine) |
| **net for 7 of 64** | **−406** |
| and the image **overflowed 8 192 B outright** with both loops present | — |

That overflow is the finding, not a build accident: the C loop **must stay** to be the fallback, so a partial port
pays for two dispatchers and removes only the cases asm handles.

Corrected economics of `vm_enter` (2 392 B today = loop 502 + 64 bodies × 29.5):

| port | arithmetic | vs today |
|---|---|---|
| 7 bodies | C 502 + 57×29.5 + asm 466 | **+258 B loss** |
| all 64 | asm 305 + 64×23 = 1 472 | −920 B |
| all 64, + ~15 helper bodies at ~30 B store/call/reload | 1 922 | **−470 B** |
| all 64, but the 5 control-flow cases must stay in C (`continue`/`return`, E-067) | C 650 + asm 1 700 | **−42 B** |

**Verdict: the prize is 40–470 B, almost certainly at the low end, against a countdown of 800 B.** The asm dispatch
core **cannot** close the blocks gap, and the earlier 719 B projection (E-068) was wrong because it assumed the C loop
would disappear; the loop can only disappear if *every* body moves, including the five that control flow and the
fifteen that call C helpers — and those cost more to port than they save.

This is the second time in this session that a projection was corrected *downward* by measurement rather than up
(`rd32`, then this). Both corrections came from measuring the thing rather than the sub-parts.

## E-071 — Experimental blocks build: every lever behind a flag; 43 B over, and one blocker isolated

Created `probe/blocks/` (shipping tree untouched). Flags, each independently revertible:

| flag | what it does | measured effect |
|---|---|---|
| `EXP_BLK` | `P33_BLOCK` + `BLKSZ 256` + block words as C primitives + `mailbox[4]` | text +≈390, dict +40 (vs +530 for the Forth layer) |
| `EXP_RINGS` | rings 32/64, `TIBSZ` 96 | −128 B bss |
| `EXP_STACK` | C-stack reserve 320 → 276 (P21 measured 244) | +44 B of pool limit |
| `EXP_SUBSET` | retire 8 hardware-adjacent primitives (WAKE MS ADC@ GPIO! GPIO@ TYPE KEY? KEY) | −≈223 B text — **but see the blocker** |
| `EXP_ASM` | hand-written dispatcher | left off (E-070: cannot pay) |

Also written: the **HP byte server** (`main/repl_main.c`, `block_task`) — polls `ulp_repl_blk_req`, reads the ULP's
mailbox through the published `ulp_repl_mb_addr`, copies to/from the block buffer at
`ulp_repl_mem_addr + ulp_repl_blk_off`, verifies the 16-bit sum on writes, and writes the status **last** so the ULP
can never read a half-copied buffer with a valid status. Backend is a RAM file (8 × 256 B) on purpose: it proves the
handshake without a flash write in the first run.

**Two things the flags proved the hard way:**

1. **`mem` and `mailbox` are `static`, so the map generator never exports them** — the host cannot reach the block
   buffer by symbol at all. It now uses addresses the ULP publishes at first run. `(u32)&mem[0]` also cannot be a
   *static initialiser* in the host build ("initializer element is not constant"), and the host build is the image
   generator, so a failing generator means the vocabulary never bakes.
2. **`EXP_SUBSET` breaks image baking.** With it: `p39_prelude.fs:25: error / IMMEDIATE?`. Without it the same tree
   bakes cleanly (`image: 1180 bytes of 1442`). The failure is isolated to the prelude's line 25
   (`: IF ['] 0BRANCH W, 0 W, HERE 2 - ; IMMEDIATE`) and is *not* caused by the retired names — none of the eight
   appears in the prelude. Cause not yet found.

**Status: the image is 43 B over** (pool 7 943 against a 7 900 limit at the 276 B stack reserve), and the one lever
that would close it (the subset, −223 B) is blocked by the baking failure. `MEMSZ` cannot shrink further: `V_HERE`
1 180 + the 256 B buffer = 1 436 is the floor and the tree is at 1 442.

**Blocks do work on the host**: with the fake server, `SRV blk0[0]=00 blk0[9]=09 blk3[9]=1e` shows the transfer and
checksum path intact.

**Next, in order:** (a) find why `P31_SUBSET` breaks the prelude at line 25 — the isolation is done and it is one
statement; (b) then the board run: `BLOCK 0`, write, `UPDATE`, `SAVE`, re-`BLOCK 0`, read back, expect the written
byte.

## E-072 — Experimental blocks build: fits (7 903/7 916) and boots; `BLOCK <n>` still errors in interpret mode

**Two blockers cleared.**

1. **`P31_SUBSET` broke the bake because `DOCOL` is declared outside the X-macro list.** My generator walked only
   the `X(...)` lines, so `P_HAVE_DOCOL` was never emitted; with `P31_SUBSET` the `case P_DOCOL:` body vanished from
   the switch, so every *call* of a colon word fell through to `default: err()`. The symptom was `IMMEDIATE?` at
   prelude line 25 — the first call of a compiled word, not its definition. Fixed by forcing `P_HAVE_DOCOL`,
   `P_HAVE_DOVAR`, `P_HAVE_DOCON`. Same class as F-98: a second derivation of an ordering. Bake now succeeds at
   **1 104 bytes**.
2. **The ring-size boot assert (E-056) fired on the real board**: `FATAL: ring size mismatch — ULP cmd=32 out=64,
   host cmd=64 out=128`. It refused to run instead of corrupting the console — the assert paid for itself exactly
   once and exactly when it mattered.

**Build and board status.** The tree fits: pool **7 903 / 7 916** at a 260 B stack reserve, `MEMSZ` 1 360,
`V_HERE` 1 104 → **256 B of app space** plus a 256 B block buffer. On the board: boots, `2 3 + .` → `5 ok`,
`HERE .` → `1 104`, and the R4 precondition still speaks (`tasks need an empty stack`).

**Still broken:** `BLOCK 0` prints `0?`, `BLOCK 1` prints `1?` — the error names the *number* that follows `BLOCK`,
while `UPDATE` and `SAVE` dispatch correctly. `BLOCK` provably runs (it emits `ERR_NO_SERVER` on a later line), so
the token maps to `p_blk_block`; what fails is the token after it. Not yet explained. Next probes, in order: call
`BLOCK` from a colon definition (`: T 0 BLOCK . ; T`) to separate interpret-mode parsing from the primitive, and check
whether `POP()` reads the cell the number pushed.

**Also measured:** raising `BLKWAIT` from 4 096 (~2 ms) to 200 000 (~100 ms) did not change the symptom, so the wait
bound is not the blocker — a 1 ms polling host answers well inside 100 ms either way.

## E-073 — Experimental blocks: the server runs and answers; `BLOCK` still errors with an empty-name `?`

**Three real bugs found and fixed, all of them board-only:**

1. **`pdMS_TO_TICKS(2)` is `0` at the default 100 Hz tick**, so `console_task` spun at priority 10 without ever
   yielding and starved `app_main` (priority 1) — the block server task was therefore **never created**, and the only
   symptom was `ERR_NO_SERVER` on the other core. Fixed: `vTaskDelay(1)` (one tick), and the server is created
   **before** the pump so a starving task cannot lose it.
2. **`xTaskCreate`'s return was ignored.** A task that fails to start must say so; it now prints the result and the
   free heap (`blocksrv up (heap 378924)`).
3. **The ULP links at address 0**, so the addresses it publishes (`&mem`, `&mailbox`) are **offsets into RTC slow
   memory**, not pointers. Dereferencing one panics: `Guru Meditation … LoadProhibited … EXCVADDR 0x00001e68`, which
   is exactly the mailbox offset. Fixed with `ULP_RAM_BASE = SOC_RTC_DATA_LOW` (0x5000_0000) plus a static assert on
   the window size.

After the fixes the server demonstrably answers: `blksrv: req #1 blk=0 op=0 sum=0`.

**Still broken:** `0 BLOCK` prints `?` — an error whose name is *empty*, meaning `err()` ran with `rd8(PAD) == 0`.
`0 BLOCK 1 BLOCK` prints `1?` (naming the second number). `2 3 + .` still gives `5 ok`, so the interpreter is fine
around it. On the **host** the same build prints `1104` for `0 BLOCK .`, so the primitive and the fake server are both
correct; the difference is on-chip only, and it is not the wait bound (tried 2 ms, 100 ms, 400 ms — unchanged).

**Also confirmed working on the chip:** the REPL precondition (`tasks need an empty stack`) still fires correctly, and
image/pool are 7 903 / 7 916 with 256 B blocks, 256 B buffer, 16 B mailbox, 60 primitives and a 260 B stack reserve.

## E-074 — R5 on the chip: blocks work end to end (`probe/blocks`, 8 047 of 8 176 B)

**Four defects, all board-only in the previous attempt, all now fixed and verified.**

1. **Primitive-id drift (F-107).** The bake ran without `P43_TASKS`, the ULP build with it, so id 59 was `BLOCK`
   in the image and `SPAWN` in the switch. `0 BLOCK` therefore ran SPAWN, which parsed the end of the line and
   printed an empty PAD → `?`. Fixed by making `src/subset.h` the single owner of every flag that changes the
   X-macro order, and by adding `_Static_assert(P_COUNT == ID_COUNT)`. The assert caught my own first guess
   (59/60/61 vs 60/61/62) in one compile.
2. **`mailbox[3]` read without `volatile` (F-108).** GCC folded the checksum load to the `0` written for a READ
   request, so zero blocks "passed" and any real block failed `ERR_CRC` while the server logged
   `file=65 buf=65 sum=65`. Fixed with a volatile lvalue.
3. **Silent data loss on a dirty buffer switch (F-109).** Now `ERR_DIRTY`, code `-7`.
4. **Debug prints interleaving with the operator's console.** Gated behind `BLK_DEBUG`, off.

**Verified on the board, clean console (`/dev/ttyACM1`, 115200):**

```
0 BLOCK .        -> 1272 ok
65 0 BLOCK C!    ->  ok
UPDATE           ->  ok
SAVE .           -> 0 ok
0 BLOCK C@ .     -> 65 ok
1 BLOCK C@ .     -> 0 ok
70 0 BLOCK C!    ->  ok
UPDATE           ->  ok
1 BLOCK .        -> ERR_DIRTY -7 ok
SAVE .           -> 0 ok
0 BLOCK C@ .     -> 70 ok
: SQ DUP * ;     ->  ok
7 SQ .           -> 49 ok
2 3 + .          -> 5 ok
```

**Budget, measured from the ELF** (`riscv32-esp-elf-size -A …/ulp_main.elf`):

| | |
|---|---|
| `.text` / `.rodata` / `.data` / `.bss` | 4 950 / 412 / 1 544 / 881 |
| total | **7 787 B** |
| + 260 B C-stack reserve | **8 047 of 8 176 → 129 B spare** |
| `MEMSZ` / `BLKADR` / `V_HERE` | 1 528 / 1 272 / 1 104 → **168 B app space** |
| blocks | 8 × 256 B, RAM-backed, one buffer, one outstanding request |

**Capability note:** this tree runs with **R4 off** (F-110). R4 costs ~496 B of text and the pool holds blocks or
tasks, not both. `probe/repl` still has R4 and a green suite.

## E-075 — `NTSK 3 -> 2`: measured −152 B, and the task bound is now proven by name

**The lever.** `NTSK` is the number of task records in `tsk[]`; each is a full 136 B VM snapshot plus
`entry`/`state`. Measured on the shipping build (`riscv32-esp-elf-size -A …/ulp_main.elf`):

| | before (NTSK 3) | after (NTSK 2) | delta |
|---|---|---|---|
| `.text` | 4 820 | 4 808 | **−12** |
| `.bss` | 964 | 824 | **−140** |
| total pool used | 7 852 | 7 700 | **−152** |
| countdown | 800 B | **648 B** | −152 |

The `% NTSK` in `vm_next_ready` was predicted to be worth more (`% 3` is a divide-by-constant vs `% 2` as a
single `and`); it measured **12 B**, not the ~40 B projected. Recorded because the projection was mine and
wrong, again in the same direction (bytes and cycles do not track code shape).

**The named failure cost 32 B back.** A full table used to call `err()`, which prints the word in PAD — the
*name being spawned* — so a third `SPAWN` reported `TA?` and looked exactly like an unknown word (the same
confusion that made the block id-drift present as a bare `?`, F-107). It now emits `ERR_TASKS` and sets
`errf`: +20 B text, +12 B rodata, countdown 648 → **680 B**. Net for the whole change: **120 B**.

**Proven on hardware** (`/dev/ttyACM1`), one session:

```
: TA 1 . PAUSE 2 . ;  : TB 3 . PAUSE 4 . ;  : TC 5 . PAUSE 6 . ;
SPAWN TA SPAWN TB              -> 1324
SPAWN TA SPAWN TB SPAWN TC     -> ERR_TASKS 1324
2 3 + .                        -> 5 ok
```

Note the semantics the test exposed: a **retired task frees its slot**, so `NTSK` bounds *concurrent* tasks,
not lifetime spawns. A separate `SPAWN TC` after the first two finished correctly succeeded — it is not a
regression.

**Regression coverage added** (`tests/ntsk.fs` + `tests/ntsk.expected`), because a deliberate error aborts a
load and therefore cannot live inside `suite.fs`. `tests/run.sh` now asserts both that the load aborts and
that the message is exactly `ERR_TASKS`.

## E-076 — Two levers landed: `-msave-restore` (−224 B) and a hash dictionary (−406 B of dictionary)

**1. `-msave-restore`, flag only.** Injected through `EXTRA_CMAKE_ARGS` because the ULP toolchain file offers no
hook; the baseline flags are extracted from IDF's own file with a regex that **fails the configure** if the shape
changes. Measured: `.text` 4 828 → 4 604.

| variant | .text | Δ |
|---|---|---|
| baseline | 4 828 | — |
| **`-msave-restore`** | **4 604** | **−224** |
| `-fno-builtin` | 4 828 | 0 |
| `-fno-stack-protector` | 4 828 | 0 |

**2. Hash dictionary (P51).** Headers moved to their own area at the top of `mem[]`, 4-byte entries
`hash20 | xt11 | imm1`, stride 4, growing down from `HDRTOP`; `find()` is one `lw` per header. The `xt` stored in
the entry points at the code field in the code area, so the dispatcher and the `xt+2` body offset are untouched.

```
before: 81 headers 730 B, names 283 B (avg 3.5 chars), link chain, byte compares
after : 81 headers 324 B, 0 names, fixed stride, 4-byte compare
bake  : image: code 570 + headers 324, free 810 (MEMSZ 1704, 81 words)   [collision check: clean]
```

`MEMSZ` unchanged at 1 704; the 406 B went straight to **app space 558 → 810 B** and the countdown
**456 → 52 B**. Text cost of the new code: +160 B (4 604 → 4 764), so the net text is +? — the flag paid for it.

**Verified on the chip** (clean console, `/dev/ttyACM1`):

```
2 3 + .                -> 5 ok
: SQ DUP * ;  7 sq .   -> 49 ok     (case-insensitive: the hash is over the upper-cased token)
: FIB DUP 2 < IF ELSE DUP 1- FIB SWAP 2 - FIB + THEN ;
10 FIB .               -> 55 ok
HERE .  LATEST .       -> 620 / 1372
: A1 11 . ;  : A2 22 . ;  LATEST .   -> 1368      (header area steps down by exactly 4 per word)
A1 A2                  -> 1122 ok
SPAWN TA SPAWN TB      -> 1324
SPAWN TA SPAWN TB SPAWN TC -> ERR_TASKS 1324
```

**Guards added with it:** bake-time **hash collision check** (a collision dispatches the wrong word and the machine
cannot report that); `image_boot_assert()` (absolute `V_LATEST` means a stale bake is a dictionary-falls-off-the-end
bug — halts with `0x51`); `_Static_assert` that `HDRTOP % 4 == 0`, since an unaligned `lw` traps.

## E-077 — Stack overflow was silent (fixed, loud), `rd16` bound wrapped (fixed), message text moved off the ULP

**Three defects, two of them correctness bugs. Measured before/after on the same tree.**

| | before | after |
|---|---|---|
| `.text` | 4 764 | **4 786** |
| `.rodata` | 372 | **268** (the jump table alone; zero message strings) |
| `.bss` | 824 | 825 |
| total pool | 7 680 | **7 599** |
| countdown | 52 B short | **FITS, 29 B spare** |

**1. `SD 16` wrapped the stack index silently.** `PUSH` wrote `ds[sp & (SD-1)]`, so the 17th value landed in
slot 0. Measured with only `-DSD` changed: `15 FIB .` answers **610 at SD 256** and **377 at SD 16**, and a
three-line Fibonacci file **hangs the machine** at SD 16 (exit 124, no output). The green suite never saw it
because it peaks at **6 data cells**; measured peaks are suite 6/7, `15 FIB` **17/15**, three tasks 3/3,
ten-number line 10/3, with the law `data = depth + 2`.
Fixed by checking the index **before** the store and reporting once at the dispatch boundary
(`ERR_STACK`, code `0x89`), where emitting is safe and the stacks can be reset: the operator loses the line,
not the session. Cost **+22 B of text, 0 pool** — `SD 32` would have cost **+394 B**, which the pool does not
have while blocks also fit.

**2. `rd16`'s bound test wrapped.** `a + 1u < MEMSZ` is true at `a = 0xFFFFFFFF` (the sum is 0), so `-1 @`
passed the check and read `mem - 1`. Now `a < MEMSZ - 1u`. `P(a)` never had the bug because it tests `a`.

**3. Message text is no longer on the coprocessor.** The ULP emits **one byte** per message (`src/msg_codes.h`,
one `MSG_LIST` X-macro that expands to enumerators on the ULP and to the string table on the HP);
`main/repl_main.c` expands it through `src/msg_expand.h`. `.rodata` 372 → **268**, and `strings` over the ULP
image returns **0** for every message. The transcript is **byte-identical**: `tests/run.sh` now pipes the
engine and `ntsk.fs` through `tools/expand.c` (which includes the same header) and compares against the
unchanged `expected.txt`.

**Verified on the board** (`/dev/ttyACM1`, clean console):

```
banner (expanded by the HP)   -> "\nulp forth\n ok\n"
2 3 + .                       -> 5 ok
BOGUS                         -> BOGUS?
10 FIB .                      -> 55 ok
15 FIB .                      -> ERR_STACK          <- and the next line still works
2 3 + .                       -> 5 ok
HERE .                        -> 612
SPAWN TA SPAWN TB             -> ok / 1324
12<BS>3 .                     -> echo "\b \b", prints 13    (0x81 erase code)
```

**Also measured, not adopted (agent findings, all reproduced or refuted by measurement):** computed goto
`-6 B` (the 268 B table is conserved — `&&label` is also 4 B); un-checking accessors as proposed **+40 B**
(only 13 body lines are safe; GCC then outlines `PUSH`); `UC_FOLD` **−14 B**, **−22 B** with computed goto
(deferred by decision); `-Oz` byte-identical to `-Os`; `-mrelax` 0; `-fno-jump-tables` +88 net;
`-fno-omit-frame-pointer` +376; `-fno-crossjumping` +386.

## E-078 — Coverage extended to every hole found, and an inventory of the levers used

**Tests: 2 → 7 checks.** Each one is tied to a specific defect and fails if the fix is reverted.

| check | hole it closes | how it fails without the fix |
|---|---|---|
| `deep.fs` | stack wrap (F-115) | `15 FIB .` → `ERR_STACK`; the trailing `888 .` never prints |
| `addr.fs` | `rd16` bound wrap (F-116) | `-1 @ .` etc. → `0000` instead of a wild read |
| `lookup.fs` | hash dictionary: case + newest-wins (P51) | `7 sq . 7 Sq .` → `4949`, redefinition → `27` |
| `ntsk.fs` | task-table bound | third `SPAWN` → `ERR_TASKS`, `888` suppressed |
| `suite.fs` | the original 26 assertions | unchanged, piped through the real expander |
| ring drain | `msg_drain_ring` "does not fit" path → livelock | order/completeness/exactly-once over a wrapping 128 B ring |
| unknown code | a code with no string must name itself | `0x8a` → `ulp: ERR_ULPCODE 0x8a (unknown code)` |

`tests/run.sh` now loops over `tests/*.fs` against `tests/<name>.expected`, so adding a case cannot be
forgotten by the runner. Error tests carry an `888 .` abort sentinel rather than the script knowing how an
abort is implemented.

**Still uncovered, named rather than implied:** `ERR_DICT` (dictionary exhaustion — needs hundreds of
definitions), `image_boot_assert` `0x51` (needs a deliberately mismatched image), a deliberate hash collision
(the bake checks every run, but no test constructs one), and the block layer's `ERR_DIRTY`/CRC paths (manual
board runs only, E-074).

**Optimisation inventory, all measured:**

| lever | result | state |
|---|---|---|
| `-msave-restore` | −224 B text | **adopted** |
| hash dictionary (P51) | −406 B dictionary | **adopted** |
| one-byte message codes | −104 B rodata | **adopted** |
| `NTSK 3→2` | −140 B bss, −12 B text | **adopted** |
| `P30_HANDCOPY`, `lhu` (P42), number-first `interpret`/`find` (P46) | −356 B / −35 % cycles / 17× on literals | adopted earlier |
| computed goto | −6 B | measured, **skipped by decision** |
| `UC_FOLD` accessors | −14 B (−22 B with cgoto) | measured, **skipped by decision** |
| `-Oz`, `-mrelax`, `-fomit-frame-pointer`, `-fira-*`, `-falign-*` | 0 | no action |
| `-fno-jump-tables` | +88 B net | rejected |
| `-fno-omit-frame-pointer`, `-fno-crossjumping`, `-fno-ipa-icf` | +376 / +386 / +22 | rejected |
| `-fno-builtin`, `-fno-stack-protector`, `-flto` | 0 (and LTO is a no-op in one TU) | no action |

Total on the table but unused: **22 B** (computed goto + folded accessors), against **29 B of spare pool**.

## E-079 — R5 + R4 in ONE image on the chip, and the four bugs that separated them from working

**Yes: blocks and multi-tasking coexist.** Measured from the ELF: `pool 7 853 / 7 856` (3 B spare),
`MEMSZ 1 200`, `BLKSZ 128`, `BLKADR 1 072`, headers 340 B, app space 154 B. On the board:

```
0 BLOCK .        -> 1072 ok        (BLKADR = MEMSZ - BLKSZ)
65 0 BLOCK C!    -> ok             UPDATE -> ok      SAVE . -> 0 ok
0 BLOCK C@ .     -> 65 ok          1 BLOCK C@ .     -> 0 ok
1 BLOCK .        -> ERR_DIRTY -7 ok (refuses to clobber unsaved edits)
SPAWN TA SPAWN TB           -> 1324
SPAWN TA SPAWN TB SPAWN TC  -> ERR_TASKS 1324
0 BLOCK C@ .     -> 70 ok          (blocks still work after tasks ran)
2 3 + .          -> 5 ok
```

**Four defects had to be fixed to get here, and every one was a "two owners" or "wrong sibling" bug:**

1. **The three primitives existed only as headers.** `p33_prims.inc` had no `X(BLOCK…)` entries and
   `p33_cases.inc` had no `case P_BLOCK:` — so the word was absent; adding only the X entries produced a
   token that found its header and fell to `default: err()`, which prints the word in PAD and looks exactly
   like "unknown word". A primitive needs **both halves**.
2. **`BLKSZ` had two owners.** The ULP built at 128, the host server kept `#define BLK_SZ 256`: every SAVE
   checksummed 256 B against the ULP's 128, nacked with a plausible code, and the extra 128 B **overwrote
   the ULP's `.bss`** — the visible symptom was a second boot banner appearing mid-session. The ULP now
   publishes `blk_sz` and the host refuses to serve a size that does not fit.
3. **Publish-on-first-run is wrong when RTC RAM survives a reset.** After a reflash, `repl_magic` still read
   "already ran", the initialisation was skipped, and the host got `blk_sz = 0` — every copy loop did
   nothing and SAVE reported `+4` (a nacked checksum over zero bytes). The addresses are now republished
   every wake.
4. **F-108 came back**: this tree's `blk_xfer` still read `mailbox[3]` non-volatile, so for a READ the load
   was CSE'd to the `0` we had just written. Empty blocks "verified" (0 == 0) and blocks with data failed
   `ERR_CRC` while the server logged `file=65 buf=65 sum=65`.

**Two traps that cost time and are worth recording:** `BLKWAIT 4096` (~2 ms) is shorter than the host's
10 ms poll, so the first request timed out and — because a timed-out request deliberately keeps `blk_out`
set — every later call answered `ERR_BUSY`; and a **`blk_sz` initialisation placed inside `#if defined
(BLK_DEBUG)`** means the size is zero in the shipping build. A variable that decides correctness is not a
diagnostic.

**Honest limits of this configuration:** 128 B blocks (not 512), 154 B of app space, and a backend that is
still an 8 x 128 B **RAM** array on the HP — **no flash, no PSRAM** (R7 unwritten; the ULP never sees either).

## E-080 — Blocks are now in `tests/`, and one of those tests cannot do its job on the host

**Added (9 checks, all green):** `tests/blocks.fs` (round trip, checksum, dirty refusal, range) and
`tests/blocks_noserver.fs` (timeout, machine survives, and the documented `ERR_BUSY` wedge). `run.sh` builds a
**second** host binary with the shipping block flags and routes `tests/blocks*.fs` to it, so the flag set
lives with the engine rather than in a test file. A `SRV ` line the driver prints at exit is filtered out of
the golden transcript — a driver diagnostic must not be part of a program's expected output.

**The honest negative result.** Reverting the volatile fix (`mb_get(3u)` → `mailbox[3]`) and re-running
`blocks.fs` **passes**: GCC does not fold that load on x86 the way it does on rv32 at `-Os`. So that test
covers the block layer's *semantics* and cannot cover the *codegen* bug, which means no host test can guard
it. The defence was changed accordingly: every mailbox access now goes through `mb_get`/`mb_set`, so the
volatile lives in one place and the mistake cannot be made again by forgetting it at a call site.
`tests/deep.fs` was mutation-checked the same way and **does** bite: with the wrap restored it prints
`55377888` instead of `55ERR_STACK `.

**Board re-verified after the refactor** (pool 7 853 / 7 856): `0 BLOCK .` → 1072, write/`SAVE 0`, read back
65, `SPAWN TA SPAWN TB` → 1324, `2 3 + .` → 5.

