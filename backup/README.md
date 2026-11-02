# Flash backup — ESP32-S3 (the esp32-rv32 / App Store board)

Taken **before** the board was swapped for the LoRa board, so the experiments on the new board can be undone.

| | |
|---|---|
| file | `esp32s3-xxxxxxxxxxxx-8MB-20261101-1653.bin` |
| size | **8 388 608 B** (the whole 8 MB flash, 0x000000–0x7FFFFF) |
| chip | ESP32-S3 (QFN56) rev v0.2, 8 MB, MAC `xx:xx:xx:xx:xx:xx` |
| port at the time | `/dev/ttyUSB0` (CP210x bridge), read at 460 800 baud |
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
sha256sum -c backup/esp32s3-xxxxxxxxxxxx-8MB-20261101-1653.bin.sha256          # must print OK before you write anything
python -m esptool --port /dev/ttyUSB0 --baud 460800 write_flash 0x0 backup/esp32s3-xxxxxxxxxxxx-8MB-20261101-1653.bin
```

`write_flash 0x0 <image>` writes the raw image straight through: what was read is what is written. After it finishes the board boots the App Store again (`./cli.py --appstore`).

## Notes worth keeping

* **921 600 baud corrupts this link.** The first attempt died at ~46 % with `expected 0x1000 bytes but received 0xff2`,
  and esptool discarded the partial file. 460 800 took 3 m 27 s and was clean. Do not "speed it up".
* The port renaming itself (`/dev/ttyACM1` → `/dev/ttyUSB0`) is why the chip identity was checked **before** trusting the
  dump: same chip family on a different bridge would have silently backed up the wrong board. The check is: read a little,
  look for this firmware, then commit to 8 MB.
