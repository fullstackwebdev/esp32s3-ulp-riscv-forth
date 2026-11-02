# probe/lora — SX1262 driven from the ULP-RISC-V (Heltec WiFi LoRa 32 V3)

Bare-metal bring-up: the **ULP-RISC-V** bit-bangs SPI, initialises the radio, transmits one 20-byte packet per timer wake,
and puts the radio back to sleep. The main core only prints counters. This exists to answer the questions in
`docs/28-sx126x-ulp.md` §4–§6 with measurements instead of estimates.

## Result (measured on the board, 2026-11-01)

```
bus probe @1MHz: transmit ESP_OK, GetStatus reply 0x2a (chipmode 2, status 5)
wakes   4  tx_ok   4  tx_fail   0  err 0  cfg tcxo  status 0x2c  spi 975 cyc/B (143 kHz SCK)  pads 1  ulp 2584 B
```

| quantity | measured | note |
|---|---|---|
| ULP image | **2 584 B** | HAL + driver + pads self-test + TX path (2 068 B before the self-test was added) |
| SPI bit-bang | **975 cycles/byte** = 122 cycles/bit = **143 kHz SCK** | from `ULP_RISCV_GET_CCOUNT()` inside the ULP, one transaction of 16 bytes |
| packets sent by the ULP alone | **4 / 4 wakes**, `TxDone` each time | 5 s ULP timer, main core never touches the bus |
| chip status read by the ULP | **0x2c** (chipmode 2 = STDBY_RC) | matches the hardware-SPI probe's `0x2a` |
| TCXO | **required**: DIO3 @ 1.8 V | cfg without TCXO never reaches `TxDone`; cfg with it does, every wake |
| DIO2 → RF switch | enabled | as configured |
| warm start | **works**: `SET_SLEEP(0x04)` retains the configuration across ULP wakes | after the first cold init, later wakes go straight to `SET_TX` and still succeed |

## What was proven, and how

1. **Pin map** (SCK 9, MOSI 10, MISO 11, NSS 8, RESET 12, BUSY 13, DIO1 14): hardware SPI on those exact pins answers
   `GetStatus` = `0x2a`, and later the ULP on the same pins answers `0x2c` *and* gets `TxDone`. Two independent paths.
2. **The radio is on the same power rail** as those pins — no Vext/rail gating to enable on this board.
3. **TCXO**: the two-configuration bring-up (no-TCXO first, then TCXO) is what answers this rather than the datasheet
   guess. `ulp_cfg_used` records which worked.

## Two bugs this bring-up paid for (now in `docs/11` as F-141/F-142)

* **`RTC_GPIO_OUT_DATA_W1TS_S` is 10.** `REG_WRITE(RTC_GPIO_OUT_W1TS_REG, BIT(pin))` writes ten bits *below* the field
  and is silently discarded: the ULP runs, the SPI loop executes, MISO reads 0, `GetStatus` returns 0x00, and every
  command "succeeds" while no pad ever moves. Four flash cycles were spent on pin maps and handover before the pad
  read-back inside the ULP showed it.
* **`RTC_GPIO_IN` only reports a pad whose input buffer is enabled** (`RTC_IO_x_FUN_IE`). A read-back self-test that
  forgets this reports "all four pads dead" for a perfectly working bus.

## Build and run

```bash
cd probe/lora
export IDF_PATH=/home/user/research/esp32/esp-idf && . "$IDF_PATH/export.sh"
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/ttyUSB0 -b 460800 flash
```

Read the console with the port **already open** before resetting, or the boot lines (including the bus probe) are lost:

```python
import serial, time
s = serial.Serial("/dev/ttyUSB0", 115200, timeout=0.2)
s.setDTR(False); s.setRTS(True); time.sleep(0.15); s.setRTS(False)   # reset, keep the port
```

The app prints for 20 s and then idles with the ULP still running. Deep sleep is the next step, not enabled here.

## Restore the board

`backup/heltec-v3-meshtastic-xxxxxxxxxxxx-8MB-20261101-1653.bin` is this board's Meshtastic firmware:

```bash
cd backup && sha256sum -c *.sha256
python -m esptool --port /dev/ttyUSB0 --baud 460800 write_flash 0x0 heltec-v3-meshtastic-xxxxxxxxxxxx-8MB-20261101-1653.bin
```

## Next

* Decode the transmitted packet on a receiver (a second node, or an SDR) — `TxDone` proves the radio transmitted, not
  that the payload is correct on air.
* Deep sleep: does the ULP timer still run and still transmit with the main core powered down? That is the actual
  months-on-a-cell question.
* Then the Forth port: the driver is 2 584 B of C in a 7 892 B pool that has **1 B free**, so this run also measures how
  much room a Forth version has to buy back.
