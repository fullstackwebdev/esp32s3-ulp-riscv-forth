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
| warm start | **works** — proven with a counter, not assumed | `cold 2` while `wakes 6`/`tx_ok 6`: exactly two cold inits ever, every later wake goes straight to `SET_TX` |
| payload in the radio's TX buffer | **matches** (`ReadBuffer` 0x1E, `buf 0`) | the SPI data path (NSS, command framing, address phase) is proven, not just "no error" |
| ULP awake window per warm transmit | **195.8 ms**, measured from the main core | predicted 185.3 ms from the datasheet formula → 105.6 % |
| ULP cycle counter | **17.55 MHz** (175 503 cycles per 10 ms delay) | accurate for short intervals; see the note below |

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
* **The cycle counter is not usable for the air-time measurement.** Calibrated at 0.3 % over 10 ms, the same
  `end - start` across `SET_TX → DIO1` returned 3.4e9 cycles (195 s) for a 108 ms-ish packet — a wrap read as a huge
  positive, even after switching to signed arithmetic. The instrument was replaced instead of trusted: the main core now
  times the ULP's awake window at 200 µs resolution, which is where the 195.8 ms comes from.
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

## Deep sleep: the CPU off, the ULP still transmitting (measured)

```
POWERON          wakes   1  tx_ok   0   cold 1
+30 s (DSLEEP)   wakes   6  tx_ok   6   cold 2   cause 4
+60 s            wakes  13  tx_ok  13   cold 2
+90 s            wakes  19  tx_ok  19   cold 2
+120 s           wakes  25  tx_ok  25   cold 2
+150 s           wakes  31  tx_ok  31   cold 2
```

Five deep-sleep cycles: **31 packets, 0 failures, and `cold` frozen at 2** - the warm configuration survives the CPU
being powered down, and the ULP's own RTC-domain timer keeps firing at 5 s while `esp_deep_sleep` has the core off. The
CPU timer here exists only so the counters can be read; the radio does not need it.

`ESP_PD_DOMAIN_RTC_SLOW_MEM` does not exist on the S3 (`SOC_PM_SUPPORT_RTC_SLOW_MEM_PD` is 0): RTC slow memory cannot be
powered down at all, which is what the ULP's variables live in. `RTC_PERIPH` is kept on explicitly, because that is where
the ULP itself lives.

## Power: what the numbers say about months (`power_budget.py`)

```
measured : ULP awake 195.8 ms per transmit, of which 185.3 ms is the packet on air (95 %)
measured : SPI 971 cycles/byte at 17.55 MHz -> 18.1 kB/s -> 144.6 kHz SCK, 55.3 us/byte

  period   packets/day   average draw    2000 mAh cell lasts
      5 s         17280        1.689 mA   49.3 days
     30 s          2880        0.290 mA   287.1 days
     60 s          1440        0.150 mA   1.5 years
    300 s           288        0.039 mA   5.9 years
```

**95 % of the ULP's awake time is the packet on air.** The interpreter's speed, the SPI clock, the driver's bytes - none of
them show up in the energy budget at this duty cycle. Months come from the **period** (and, second, from air time via
spreading factor and payload), not from making the bus faster. Currents other than the measured timings are
datasheet-typical and labelled as such in the script: there is no current meter on this bench, and a power budget built
from unlabelled numbers is how "months on a battery" turns into a marketing sentence.

## Air time, derived (and why the first number was wrong)

Tsym = 2^9 / 125 kHz = 4.096 ms · preamble (8 + 4.25)·Tsym = 50.18 ms · payload symbols
8 + ⌈(8·20 − 4·9 + 28 + 16)/(4·9)⌉ · **(CR + 4)** = 33 → 135.17 ms · **total 185.34 ms**. Measured 195.8 ms = 105.6 %.
The `(CR+4)` factor is the one that got dropped the first time, which is how a 185 ms packet became a "~108 ms"
expectation in a comment — and why the measured number looked wrong when it was the arithmetic that was wrong.

## Next

* Decode the transmitted packet on a receiver (a second node, or an SDR) — `TxDone` proves the radio transmitted, not
  that the payload is correct on air.
* Deep sleep: does the ULP timer still run and still transmit with the main core powered down? That is the actual
  months-on-a-cell question.
* Then the Forth port: the driver is 2 584 B of C in a 7 892 B pool that has **1 B free**, so this run also measures how
  much room a Forth version has to buy back.
