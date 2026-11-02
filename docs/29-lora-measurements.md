# 29 — LoRa on the ULP-RISC-V: every measured number, one place

Everything below was measured on the **Heltec WiFi LoRa 32 V3** (ESP32-S3 + SX1262) on 2026-11-01, running
`probe/lora` — a bare-metal ESP-IDF 5.4 project where the **ULP-RISC-V alone** bit-bangs SPI, configures the radio,
transmits, and sleeps it again. The main core only prints counters and (in the deep-sleep run) stays powered down.

Provenance: `probe/lora/results/console-2026-11-01.txt` is a verbatim console capture from the running board. Anything
in this file not traceable to that capture or to a command shown here is **labelled derived or datasheet-typical**, and
nothing else is allowed in.

Board identity (R16 — an identity, not a substring hit): `Chip is ESP32-S3 (QFN56) (revision v0.2)`,
`MAC xx:xx:xx:xx:xx:xx`, 8 MB flash, on `/dev/ttyUSB0` (CP210x bridge). Its factory firmware (Meshtastic) is backed up as
`backup/heltec-v3-meshtastic-xxxxxxxxxxxx-8MB-20261101-1653.bin`, sha256 `081a90fb…c922392`, restore verified.

---

## 1. Hardware facts, established by measurement

| fact | how it was established | value |
|---|---|---|
| pin map | hardware SPI on those pins answers `GetStatus` | SCK 9, MOSI 10, MISO 11, NSS 8, RESET 12, BUSY 13, DIO1 14 |
| radio responds | `GetStatus` (0xC0) reply | **0x2a** → chipmode 2 = STDBY_RC, status 5 |
| TCXO | two-config cold init: without, then with | **required**, on DIO3 at **1.8 V**; without it no `TxDone` ever |
| DIO2 → RF switch | enabled; TX completes | works |
| DC-DC regulator | `SetRegulatorMode(1)` | works |
| radio's power rail | no gating needed on this board (radio answered from cold boot) | always on |

The TCXO result is the one worth keeping: it came from trying both, not from a datasheet guess, because a wrong choice is
indistinguishable from dead SPI from the outside.

## 2. ULP-RISC-V: size, clock, bus

| quantity | value | source |
|---|---|---|
| ULP image (HAL + driver + TX + self-tests) | **2 804 B** | `riscv32-esp-elf-size ulp_lora.elf` → text 2804, bss 56 |
| ... same image with the 2026-11-01 cross-firmware probe | **2 904 B** | +100 B: one store and two reads per wake, added to answer docs/30 F-158; the driver and every timing below are unchanged |
| ULP clock | **17.550 MHz** | 175 503 cycles measured across a 10 ms `ulp_riscv_delay_ms` (nominal 17.5 MHz, +0.29 %) |
| bit-banged SPI | **971 cycles/byte** = 121.4 cycles/bit | `ULP_RISC_V_GET_CCOUNT()` around one 16-byte transaction |
| → effective clock | **144.6 kHz SCK**, 18.1 kB/s, 55.3 µs/byte | derived: `bytes/s = 17.55e6/971`, `SCK = 8·bytes/s` |
| safe-fastest attempt | `-O2` on the HAL translation unit | no change to 971; the loop is not compiler-bound at `-Og`→`-O2` here |
| command overhead | unmeasured separately | included in the awake window |

For reference, the forum figures this replaces were "235 kHz with the helper API, 350 kHz with direct register writes"
(docs/27). This build uses direct register writes and gets 144.6 kHz — so **the forum numbers were not reproduced**; they
remain unverified claims, and this is the number for *this* code on *this* chip.

## 3. Airtime and payload

Modem settings as configured and confirmed by the air time: **SF9, BW 125 kHz, CR 4/5, preamble 8, CRC on, explicit
header, 20-byte payload, +14 dBm, 868.1 MHz**.

| quantity | value | derivation |
|---|---|---|
| symbol time | 4.096 ms | `2^9 / 125 kHz` |
| preamble duration | 50.18 ms | `(8 + 4.25) · Tsym` |
| payload symbols | **33** | `8 + ⌈(8·20 − 4·9 + 28 + 16)/(4·9)⌉ · (CR+4) = 8 + 5·5` |
| payload duration | 135.17 ms | `33 · Tsym` |
| **predicted air time** | **185.34 ms** | preamble + payload |
| **measured ULP awake window** | **195.8 ms** | timed by the main core at 200 µs resolution |
| agreement | **105.6 %** | the modem is configured as claimed |
| payload integrity | **exact match** | `ReadBuffer` (0x1E) returns what was written (`buf 0`) |
| ULP compute inside the window | ~10.5 ms = **5 %** | measured window − predicted air time |

The `(CR+4)` factor is what got dropped in the first draft of this document's predecessor, turning 33 payload symbols into
14 and 185 ms into a "~108 ms" expectation — F-144.

## 4. Sleep behaviour (measured)

Warm start retention, and the ULP running with the CPU powered down:

| event | ULP wakes | packets sent | cold inits | failures |
|---|---|---|---|---|
| POWERON | 1 | 0 | 1 | 0 | <!-- printed before the first transmit finished; see note -->
| +30 s (DSLEEP wake, cause 4) | 6 | **6** | 2 | 0 |
| +60 s | 12–13 | **13** | 2 | 0 |
| +90 s | 19 | **19** | 2 | 0 |
| +120 s | 25 | **25** | 2 | 0 |
| +150 s | 31 | **31** | 2 | 0 |

* ULP timer period **5 s**, CPU deep-sleep period **30 s**, five cycles observed, **31/31 packets, 0 failures**.
* The `POWERON` row's `tx_ok 0` is the warm-up sample: the first wake's transmit was still in flight when the line printed,
  and it lands as packet 1 by the next sample. It is left in rather than smoothed away, and the verification script
  asserts `tx_ok == wakes` only from wakes ≥ 6.
* `cold` stays at **2** (the first wake tried no-TCXO, failed, then TCXO) → **the warm configuration survives the CPU being
  powered down** and is reused on every later wake.
* On the S3 `ESP_PD_DOMAIN_RTC_SLOW_MEM` does not exist (`SOC_PM_SUPPORT_RTC_SLOW_MEM_PD == 0`): RTC slow memory — where the
  ULP's variables live — cannot be powered down at all. `RTC_PERIPH` is held on explicitly; that is where the ULP lives.

## 5. Power budget (`probe/lora/power_budget.py`)

Measured timings × **datasheet-typical** currents (no meter on this bench — labelled, not hidden): 45 mA TX at +14 dBm
with DC-DC, 0.6 µA radio warm sleep, ~10 µA CPU deep sleep, ~5 mA ULP running, 3.7 V cell.

| period | packets/day | average draw | 2000 mAh cell lasts |
|---|---|---|---|
| 5 s | 17 280 | 1.689 mA | 49 days |
| 10 s | 8 640 | 0.850 mA | 98 days |
| 30 s | 2 880 | 0.290 mA | **287 days** |
| 60 s | 1 440 | 0.150 mA | **1.5 years** |
| 300 s | 288 | 0.039 mA | 5.9 years |
| 900 s | 96 | 0.020 mA | 11.5 years |
| 3600 s | 24 | 0.013 mA | 17.7 years |

**95 % of the ULP's awake window is the packet on air.** Consequences that decide the design:

* months come from the **transmission period**, then from **air time** (SF, payload length);
* the SPI clock, the driver's byte count and the interpreter's speed are **not** in this budget at any sane period;
* the radio's warm sleep (0.6 µA) and the CPU's deep sleep (~10 µA) are small enough that both disappear next to a single
  transmit — the 5 s column is 1.7 mA purely because it transmits 17 280 times a day.

## 6. What this means for a Forth driver

| | C (measured) | Forth (projected, docs/28 §4) |
|---|---|---|
| driver size | **2 804 B** | a phase of ≤ 1 037 B + 3–4 primitives |
| SPI clock | 144.6 kHz measured | 30–80 kHz derived from token cost |
| share of a packet's cost | 5 % of the awake window | 5–10 % of the awake window |
| share of the power budget at 60 s period | 0.25 % of 1.5 years... i.e. nothing | still nothing |

The speed question is **closed**: at 5 % of a window that is 5 % of the budget, a 4–10× slower bus is noise. The open
question is purely **bytes**: the Forth pool is 7 892 B with **1 B free**, so a LoRa driver either evicts something from
the interpreter or lives as a phase with a few C primitives (pin write/read, µs delay, bit loop).

## 7. Open, named

1. **No receiver has decoded the packet.** `TxDone` + air-time agreement + TX-buffer read-back is strong, but a second
   node or an SDR is the last word on the bits on air.
2. **The ULP cycle counter is not usable for long intervals**: calibrated to 0.29 % over 10 ms, it reported 3.4e9 cycles
   (195 s) across `SET_TX → DIO1`, signed arithmetic included (F-143). The main core's clock replaced it.
3. **Current draws are datasheet-typical.** A meter would turn §5 from a budget into a measurement.
4. **`-O2` did not change the bit loop**; whether a better loop (unrolled, single-register writes per bit) buys a faster bus
   is untested — and, per §5, would not change the power answer.

## Self-reception does not work here, and the measurement says why

Tried on the current image, so that the record does not read like an untested wish: the Forth driver
transmits, then `SetRx` 10 ms later (every line under the 63 B console ring, composed from the
driver's own words so no dictionary space was needed), then reads `GetIrqStatus`.
**IRQ = 2 (measured)** - `RxTimeout`, not `RxDone`. That is the datasheet-consistent answer for a
board whose RF front end is half duplex: the receive path is switched out while the transmitter is
up, and by the time it turns around the frame is gone. So the loopback is not evidence the frame
went over the air, and it must not be dressed up as an outside receiver: what it does prove is that
the radio is answering over the SPI the coprocessor owns, with a per-command status word that is the
chip's own, and it is a *named* negative rather than a silent one.

The clause the objective asks for - "established by the radio **and by an outside receiver**" - is
therefore still open until something independent of this board listens on 868 MHz: a second node or
an SDR. `lsusb` on this machine shows only the CP210x UART bridge (the Heltec's own console) and a
mouse (measured this turn); `/dev/ttyACM*` does not exist, and `/dev/ttyUSB0` *is* the transmitting
board, which cannot listen to itself.

## Two-board test: the frame crosses BOTH ways (2026-11-02, measured)

Both Heltec V3 boards run the same firmware (`probe/repl`, the ULP Forth REPL) and the same Forth driver
(`examples/apps/lora/lora1.fs` + `lora_rx.fs`). The second board was backed up first
(`backup/esp32s3-xxxxxxxxxxxx-8MB-20261102-0837.bin`, three reads agreeing).

    A->B: SEND answered [1, 1, 1] (TxDone from the chip's own irq), B decoded 2 frame(s)
    B->A: SEND answered [1, 1, 1], A decoded 2 frame(s)
    PASS  the frame crosses between two boards in both directions, decoded by the chip's own CRC

Repeatable (two consecutive runs, same counts). The receiving side's own words report it: `IQ` = **0x0016**
(RxDone|PreambleDetected|HeaderValid), `RL` returns the length and buffer offset, `RB` prints the payload bytes read
out of the radio's RX buffer. Frequency `0x36419999` = **868.1 MHz** (868.1e6 × 2^25 / 32e6), SF9, BW 125 kHz, CR 4/5,
CRC on, 8-symbol preamble - the same parameters as the C driver.

### The bug that hid all of this, and the wrong conclusion it produced

`GetIrqStatus` reports **only** the sources enabled in the `SetDioIrqParams` mask. `INIT` set the mask to `0x0201`
(Timeout|TxDone) - so on the receive side the status word answered `0x0000` **forever**, whatever arrived:

| configuration | what the receiver reported after four frames from the adjacent board |
|---|---|
| mask `0x0201` (as shipped) | `IRQ 0x0000` - "nothing heard" |
| mask `0xFFFF` | `IRQ 0x0016` = RxDone + PreambleDetected + HeaderValid |

I spent this session concluding the opposite, and it is worth writing down how, because every one of those
measurements was real and every one pointed the wrong way once the mask was wrong:

* instantaneous RSSI (`GetRssiInst`) read `210`/`212` = -105 dBm across **234 samples** while a 14 dBm transmitter sat
  next to it. It never tracked the neighbour; with the mask fixed the same radio decodes those frames. **RSSI was a
  red herring** - do not use it as the witness for "is anything arriving".
* a finite 64 ms RX timeout produced no `Timeout` interrupt, and `SetRx` left chipmode at 5 - both consistent with a
  deaf radio, and both explained afterwards by the same masked status word.
* the *C* driver that "proved" 31/31 packets carries the identical bug (`0x0201`): it was transmit-only by
  construction, which is why it never noticed. Corrected in `probe/lora/main/ulp/sx126x_min.c`, and
  `tests/lora_spi.py` - which compares the Forth driver's wire bytes against that reference - updated in the same
  commit, with the reason recorded there rather than the expectation quietly relaxed.

Two smaller measurement traps, both gated now:
* a **250 ms windowed** listen (`RX1` per host command) missed four frames sent 400 ms apart, because each attempt
  cost a host round trip; **continuous** receive (`RC SR` once, then poll `IQ`) caught the first frame. A listener
  must stay listening (`tests/lora_two_board.py` now does).
* the payload print interferes with console parsing: ask the board **one** question per attempt and read the
  trailing integer, or a decoded frame's own bytes look like an answer.

**Memory, measured, because it decided this test:** fresh dictionary `HERE 786 LATEST 2114` = **1 328 B free**;
driver alone leaves `HERE 1814 LATEST 2033` = **219 B** (283 B after dropping constants used zero or once - a
CONSTANT only pays from ~7 uses); after `SEAL` the phase window measured `LATEST - bh @` = **219 B**. **Phases do not
expand memory**: they are the same space, sealed, and the prompt is the roomiest place to load a driver. The only
lever is a smaller driver. With driver + receive words loaded, `HERE 1 972 LATEST 2 033` = **61 B spare**.
