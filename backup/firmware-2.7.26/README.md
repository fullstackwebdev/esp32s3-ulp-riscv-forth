
## firmware-2.7.26 — the peer's current build, as flashed

Taken from `meshtastic/firmware` release **v2.7.26.54e0d8d** (`firmware-esp32s3-2.7.26.54e0d8d.zip`, fetched through
`tools/fetch.py`, so the 163 MB zip is a cached object and the four heltec-v3 files are extracted here). The release's own
`.mt.json` lists md5s, and all three images match it.

Flashing this board needs **two** writes, and the second one is easy to miss:

```
esptool.py --chip esp32s3 -p <port> -b 460800 write_flash 0x0      firmware-heltec-v3-2.7.26.54e0d8d.factory.bin
esptool.py --chip esp32s3 -p <port> -b 460800 write_flash 0x670000 littlefs-heltec-v3-2.7.26.54e0d8d.bin
```

`0x670000` is the `spiffs` offset read out of the partition table embedded at 0x8000 of the factory image — not a guess.
With only the factory image written, the app boots but never completes the client handshake ("Timed out waiting for
connection completion"), which looks like a dead board rather than a missing filesystem.

After flashing, the configuration is factory-default (region `UNSET`): set the region before expecting anything on air.
