# Flash backup — Heltec V3 (LoRa board), **not** the App Store board

> **Correction, same day.** This backup was first recorded as the ESP32-S3 that runs the App Store firmware. It is not.
> The board that answered on `/dev/ttyUSB0` is a **Heltec V3 (ESP32-S3 + SX1262)** running **Meshtastic**, built with
> `arduino-lib-builder` on ESP-IDF v4.4.7. The identification that "passed" was four substring hits for
> `uforth|ULPCODE|BLKXFER|APP STORE|repl` — and all four were the word **`repl`, inside stock IDF strings**. The App
> Store board had already been unplugged by then (its `/dev/ttyACM1` native-USB console was gone, which is why the console
> on this board looked dead at 115200 baud: Meshtastic talks over USB-CDC, not UART0).
>
> **So the App Store machine's flash was NOT captured.** The dump below is still worth keeping — it is the factory/DEMO
> firmware of the LoRa board, and it is the thing to restore when the LoRa experiments are over. Capturing the App Store
> board needs it plugged back in; see "Capturing the App Store board" at the end.

| | |
|---|---|
| file | `heltec-v3-meshtastic-xxxxxxxxxxxx-8MB-20261101-1653.bin` |
| what it is | Heltec V3 (ESP32-S3, SX1262) — **Meshtastic** firmware, `esp-idf: v4.4.7 38eeba213a` / `arduino-lib-builder` |
| size | **8 388 608 B** (the whole 8 MB flash, 0x000000–0x7FFFFF) |
| chip | ESP32-S3 (QFN56) rev v0.2, 8 MB, MAC `xx:xx:xx:xx:xx:xx` |
| port | `/dev/ttyUSB0` (CP210x bridge), read at 460 800 baud |
| sha256 | `081a90fbda2742a5bc85552b805cfd1526a95fd768fa7dc80a11c7400c922392` |

Verified two ways, not just "the file exists": a fresh 64 KB read of `0x10000` compared **identical** to the same
offset in the dump, and the dump's own structure parses — bootloader magic `0xE9` at 0x0, partition table `0xAA50` at
0x8000, app magic `0xE9` at 0x10000:

```
nvs        type 1 sub 2    0x009000    20 KB
otadata    type 1 sub 0    0x00e000     8 KB
app0       type 0 sub 16   0x010000  3264 KB
app1       type 0 sub 17   0x340000  3264 KB
spiffs     type 1 sub 130  0x670000  1536 KB
coredump   type 1 sub 3    0x7f0000    64 KB
```

Everything is in there: both OTA slots, NVS (calibration), and the block store the firmware writes (433 written 4 KB
pages between 1 MB and 4 MB) — so restoring this puts the machine back exactly as it was left, block store included.

## Restore

```bash
cd /home/user/research/esp32-rv32
export IDF_PATH=/home/user/research/esp32/esp-idf && . "$IDF_PATH/export.sh"
sha256sum -c backup/heltec-v3-meshtastic-xxxxxxxxxxxx-8MB-20261101-1653.bin.sha256          # must print OK before you write anything
python -m esptool --port /dev/ttyUSB0 --baud 460800 write_flash 0x0 backup/heltec-v3-meshtastic-xxxxxxxxxxxx-8MB-20261101-1653.bin
```

`write_flash 0x0 <image>` writes the raw image straight through: what was read is what is written. After it finishes the board boots the App Store again (`./cli.py --appstore`).

## Notes worth keeping

* **921 600 baud corrupts this link.** The first attempt died at ~46 % with `expected 0x1000 bytes but received 0xff2`,
  and esptool discarded the partial file. 460 800 took 3 m 27 s and was clean. Do not "speed it up".
* The port renaming itself (`/dev/ttyACM1` → `/dev/ttyUSB0`) is why the chip identity was checked **before** trusting the
  dump: same chip family on a different bridge would have silently backed up the wrong board. The check is: read a little,
  look for this firmware, then commit to 8 MB.

## Capturing the App Store board (needs it plugged in, ~3 minutes)

```bash
cd /home/user/research/esp32-rv32
export IDF_PATH=/home/user/research/esp32/esp-idf && . "$IDF_PATH/export.sh"
python -m esptool --port /dev/ttyACM1 --baud 460800 flash_id          # note the MAC
python -m esptool --port /dev/ttyACM1 --baud 460800 read_flash 0x0 0x800000 backup/appstore-<mac>-8MB-<date>.bin
```

**Identify before committing to 8 MB** — the check that actually works is the app description string at
`0x10000 + 0x30`, which for our firmware is not an `esp-idf:` line, plus a full-region hash compared against
`probe/repl/build/*.bin`. Do not use substring counts: `repl` is in every IDF image.
