# Handoff — Meshtastic interoperability for the ULP-RISC-V Forth LoRa stack

Written at the end of a long session in which **one direction was achieved** (stock Meshtastic → our stack) and the
other (our stack → stock Meshtastic) was **not**. This letter records everything: the setup, every experiment and its
result, the real bugs that were found and fixed, the instrumentation traps that produced false negatives, and the ranked
hypotheses for whoever picks this up.

Read `docs/14-probe-rules.md` first — the project's probe rules (R1–R35) exist because each one cost a real measurement.
Then read Appendix N of `docs/31-meshtastic-fit.md`, which this letter supersedes and extends (N.10–N.13 are from this
session).

---

## 1. Background: what this project is

`esp32-rv32` is a research repo that runs **Forth on the ESP32-S3's ULP-RISC-V coprocessor**. The ULP owns an SX1262
LoRa radio over SPI; the main cores only build and serve the program image. Applications are Forth sources in
`examples/apps/lora/*.fs`, typed into a REPL served over the board's USB-serial bridge, or packaged into a store/phase
image.

The end goal of this line of work: **a Meshtastic-compatible node whose entire radio + crypto path runs in Forth on the
ULP**, able to exchange messages with an unmodified Meshtastic node in both directions.

Already proven in earlier sessions (do not re-derive):

* The SX1262 driver works: transmit, receive, IRQ handling, buffer adopt, register read-back.
* AES-128-CTR is implemented **in Forth, split across six store phases** (seed → sub → sr → mc → ark → out), and proven
  end-to-end: `tests/aes_chain_steps.py` (46 stages, 0 failures) and `tests/mesh_air.py` (7/7).
* The cryptographic construction matches real Meshtastic traffic: a live captured frame was decrypted with our nonce +
  PSK to `Data{portnum TEXT_MESSAGE_APP, "hello from mesh"}` — byte exact. The encrypted region is the `Data` message,
  not a `MeshPacket` wrapper.
* Frame construction is validated by **Meshtastic's own Python library**: `tests/mesh_frame_check.py` 12/12 (header
  layout, flag bits, nonce, `mesh_pb2.Data`, canonical re-encode, channel byte).
* Our own on-air bytes are proven: `tests/mesh_loop_check.py` — one board transmits, the other decodes a frame
  **byte-identical** to the built one, `IRQ 0x0016`.

## 2. Hardware, ports, firmware

Two identical **Heltec WiFi LoRa 32 V3** boards (ESP32-S3 + SX1262 + CP2102 USB-serial), both on one USB hub.

| board | MAC | Meshtastic node id |
|---|---|---|
| A | `xx:xx:xx:xx:xx:xx` | `0x02AAAAAA` = 44739242 |
| B | `xx:xx:xx:xx:xx:xx` | `0x02BBBBBB` = 45857723 |

**Ports swap between sessions and are meaningless.** Identify by MAC every time:

```bash
export IDF_PATH=/home/user/research/esp32/esp-idf && . "$IDF_PATH/export.sh"
for p in /dev/ttyUSB0 /dev/ttyUSB1; do printf "%-14s " $p; esptool.py --chip esp32s3 -p $p -b 460800 read_mac 2>&1 | grep '^MAC'; done
```

At handoff both boards run **stock Meshtastic 2.7.26.54e0d8d**, region `EU_868`, preset `LONG_FAST`, and (last set)
`lora.tx_power 14`. Verify before trusting anything below.

Flash our stack (branch `ulp-meshtastic`):

```bash
cd probe/repl && idf.py -p <port> -b 460800 flash      # expect 3 × "Hash of data verified"
```

Flash stock Meshtastic 2.7.26 — **two writes are mandatory** (app + filesystem; with only the app the node boots but
never completes the handshake):

```bash
esptool.py --chip esp32s3 -p <port> -b 460800 write_flash \
  0x0      backup/firmware-2.7.26/firmware-heltec-v3-2.7.26.54e0d8d.factory.bin \
  0x670000 backup/firmware-2.7.26/littlefs-heltec-v3-2.7.26.54e0d8d.bin
```

460800 baud only; 921600 corrupts this link. After flashing, region is `UNSET` and must be set.

SX1262 wiring on this board (from Meshtastic's own `variants/esp32s3/heltec_v3/variant.h`, matches ours): NSS 8,
SCK 9, MOSI 10, MISO 11, RST 12, BUSY 13, DIO1 14; `SX126X_DIO2_AS_RF_SWITCH` defined; TCXO 1.8 V on DIO3.

## 3. The RPEL stack, and the files that matter

* `examples/apps/lora/lorainit.fs` — the configuration table + `RADIO-INIT` (used for receiving).
* `examples/apps/lora/lora_rx.fs` — `RC`/`SR`/`IQ`/`RL`/`RB`/`RXTAKE`/`RX1` receive words.
* `examples/apps/lora/loratx.fs` — the reference transmit table + `GO`.
* `examples/apps/lora/loratx_ms_final.fs` and the generated `loratx_ms_*.fs` variants — Meshtastic-frame transmitters.
* `examples/apps/lora/sync.conf` — **single source of truth for the sync pair** (enforced by linter R34).
* `probe/repl/tools/lint_forth.py` + `lintgate.py` — the linter that gates tables (R30–R35).
* `probe/repl/tests/lint_rules_selftest.py` — mutation tests proving the rules fire (currently 6/6).

A typed line is limited to 63 bytes (R21) and a definition must fit one 92 B block (R11); `HERE` must stay even (R28).
A `0 C,` parity filler **is a table iteration** — if you add one, the walker count must cover it.

## 4. Verdict at handoff

| direction | result | evidence |
|---|---|---|
| stock Meshtastic → our stack | **works** | `IRQ 0x0016` (RxDone+HeaderValid) on 2–3 of 4 frames, RSSI −18 dBm, SNR ≈6 dB |
| our stack → stock Meshtastic | **never** | 0 decodes over hundreds of frames across every parameter we control |

Both stock receivers are demonstrably alive: stock↔stock exchanged text both ways in the same session (8 and 6 decodes;
earlier 6/6 each way). So this is not a dead receiver on their side, and not a dead board on ours — swapping which
physical board runs our firmware changes nothing.

## 5. Measured constants (do not derive these)

| constant | value | how it was measured |
|---|---|---|
| carrier (our chips' coordinate) | **869.480 MHz**, word `0x3657AE14` | our receiver decodes their frames 3/4 here; 869.4343 / 869.4113 / 869.5257 give 0/4 |
| carrier (Meshtastic source formula) | **869.525 MHz** | `freqStart + bw/2000 + slot*slotWidth`, EU_868, 1 slot at BW250 |
| sync pair | **0x0740=0x14, 0x0741=0x24** | sweep of 512 candidates against a live packet; LSB must be 0x24 |
| channel hash byte | **0x08** | runtime preset name hashes to 0x08; the stored empty name hashes to 0x02 (the old bug) |
| modem | SF11 / BW250 (code `0x05`) / CR4-5 / LDRO 0 | our receiver decodes their frames with exactly this |
| preamble | 16 symbols | their `preambleLengthDefault`; our measured preamble→header 210 ms matches |
| flags | `0x63`; `0x6B` for want_ack | captured frames |
| PSK | `d4f1bb3a20290759f0bcffabcf4e6901` (default) | decrypted a live frame with it |
| nonce | `packetId u64 LE ‖ from u32 LE ‖ 4 zeros` | proven by decryption |
| header layout | `to(4) from(4) id(4) flags(1) channel(1) next_hop(1) relay(1)` | captured frames + their library |

A 32-byte text frame looks like: `ffffffff 24beea02 1d4a3b2c 63 08 0000 <ciphertext>`.

## 6. Receive direction — the evidence

* After loading `lorainit.fs` + `lora_rx.fs`, `RADIO-INIT` returns 1, `STAT` reads `0x52` (RX mode).
* Three peer `--sendtext` sends → `IQ` reads `0x0016` twice, `0x0004` (preamble only) once.
* `GetPacketStatus`: RSSI −18 dBm, SNR 6 dB.
* A 100 s listen with the peer broadcasting every 30 s produced decodes but the *same* background rate of
  "preamble detected" lines as silence — see the trap section.
* Receive was **dead (`0x0000` on every packet) for a stretch of this session** and was restored by fixing the table walk
  (bug 2 below). If your receiver reports `0x0000`, check that `SetDioIrqParams` is inside the walked range before
  anything else.

## 7. Transmit direction — the complete experiment log

Every run below had `TxDone` (IRQ bit 0) confirmed after each `GO`, and every run counted decodes on the stock node's
own device log (`security.debug_log_api_enabled true`) plus its CLI output, not our inference.

| axis | values tried | frames per point | stock-node reaction |
|---|---|---|---|
| power | −9, −5, 0, 5, 10, 14, 17, 22 dBm | 4–12 | none |
| preamble | 16, 32, 64, 128, 255, 1024 symbols | 4–20 | only the background preamble lines |
| carrier | 869.400/440/460/480/500/520/540/560 then 869.380…869.600 in 10 kHz steps (23 points) | 4–6 | none |
| PA config | `(duty,hpmax,sel)` = (2,2,0), (4,7,0), (4,7,1), (2,2,1), (7,7,0), (5,2,0) | 5–8 | none |
| LDRO | `0x00`, `0x08` (SX127x form), `0x01` (SX126x form) | 8 | none |
| IQ | standard, inverted | 8 | none |
| sync | `0x14/0x24` (measured), `0x2B/0x24` | 6–10 | none (0x2B produced no detections at all) |
| frame content | our 32 B text frame; **the stock node's own 27 B frame replayed byte-for-byte**; that frame with `from` replaced by ours; a 17 B minimal frame | 4–10 | none |
| roles | our stack on board B then on board A | 12 | identical (none) |
| peer `frequency_offset` | +0.0457, −0.0457, 0 MHz | 8 | none (note: only takes effect after reboot) |
| peer preset | LONG_FAST, and LONG_SLOW (SF12/BW125, LDRO `0x01`, carriers 869.525/869.535/869.550 and the derived 869.5875) | 6 | none |
| flood | 70 back-to-back frames over ~20 s | 70 | no log line, `channel_utilization` stayed 0.000000 |

What the stock node *did* log, in total, across all of the above: occasional `Ignore false preamble detection`, at the
same rate as with no transmission at all. It never logged `Ignore false header detection`, never logged an `Ignore
received packet due to error=…`, and never logged `No suitable channel found for decoding, hash was 0x…` — the last of
which their `Router.cpp:1005` emits for any packet that reaches the router. Conclusion: their radio never delivers a
packet to their router.

A continuous-wave test (opcode `0xD9`, `SetTxContinuousWave`) **did not work** — `STAT` stayed `0xA2` (standby), so the
carrier was never transmitted and any conclusion from it would be invalid. That test is still open.

## 8. Controls that make those negatives meaningful

1. **Our receive path decodes them** (2–3 of 4, `0x0016`, −18 dBm) using the same table family we transmit with.
2. **Our transmit is decoded by our own second board** 4 of 4 at −19…−22 dBm; the on-air frame is byte-identical to what
   Meshtastic's own library builds from the same text.
3. **Stock↔stock works both ways** in the same session (8 and 6 decodes), so both stock receivers and transmitters are
   healthy.
4. **Register read-back after our init**: `0x0740/41 = 0x14/0x24`, `0x08D8 = 0x5E` (clamp), `0x08AC = 0x96` (boosted RX
   gain, receive table) / `0x94` (chip default, transmit table), `0x08E7 = 0x38` (OCP ≈162 mA), `0x08B5 = 0x04`.
   Meshtastic patches `0x08B5` bit 0 to `0x05` for receive sensitivity; that is receive-only and we do not need it yet.

**The one measured anomaly**: at the *same* receiver, their 14 dBm arrives at −18 dBm, ours at 14 dBm arrives at
−23 dBm, and ours at 22 dBm arrives at only −22 dBm (i.e. it stops scaling above roughly 15 dBm). Our own receiver
decoding our own transmission is, however, a near-field measurement (two boards inches apart on one hub), so treat the
absolute level with suspicion and the *scaling* with interest.

## 9. What Meshtastic's own source says (cached at `probe/results/ms-src`)

* `RadioLibInterface.h`: `syncWord = 0x2b`, `preambleLengthDefault = 16`.
* `SX126xInterface.cpp:369`: on ESP32 `startReceive()` **always** calls
  `startReceiveDutyCycleAuto(preambleLength, 8, IRQ_RX_FLAGS)` — receive is duty-cycled, never continuous.
* `RadioLibInterface.cpp:123 receiveDetected()`: logs `Ignore false preamble detection` when HEADER_VALID has not arrived
  within 2 × preamble time. This is the *only* symptom we ever see from them.
* `RadioLibInterface.cpp:600 handleReceiveInterrupt()`: logs at ERROR `Ignore received packet due to error=%d …`, at
  WARN `Ignore received packet too short`, and at WARN `Ignore received packet without sender`.
* `Router.cpp:1005`: `No suitable channel found for decoding, hash was 0x%x!` — never observed.
* `CryptoEngine.cpp:379`: `Use AES%d key!` is logged **once at key setup**, not per packet. Seeing it means nothing.
* `RadioInterface.cpp:143` `RDEF(EU_868, 869.4f, 869.65f, 10, 27, …, PROFILE_EU868)`;
  `PROFILE_EU868 = {PRESETS_EU_868, 0, 0, …}`; centre = `freqStart + bw/2000 + channel_num*freqSlotWidth` with
  `channel_num = hash(channelName) % numFreqSlots` → **869.525 MHz** at BW250 (1 slot) and 869.5875 MHz at BW125
  (2 slots, empty-name hash → slot 1).
* `variants/esp32s3/heltec_v3/variant.h`: pin map and `SX126X_DIO2_AS_RF_SWITCH` (quoted in §2).

## 10. Bugs found and fixed this session (all silent, all now gated)

1. **PA configured for the wrong power band.** `SetPaConfig` was pinned at `paDutyCycle 0x02 / hpMax 0x02` (the ≤17 dBm
   setting) while `SetTxParams` asked for 22 dBm. Measured: our 22 dBm arrived at **−35 dBm** where a stock node's 14 dBm
   arrived at **−33 dBm** — i.e. we radiated *less* than the node we were trying to reach. Fixed by using `0x04/0x07`
   above 17 dBm, and now a hard lint error: **R35**, mutation-tested in `tests/lint_rules_selftest.py`.
2. **`SetDioIrqParams` fell outside the walked table.** In `lorainit.fs` the walk ran 18 entries while the interrupt
   mapping sat at index 20, so the chip was in RX (`STAT 0x52`) but the IRQ status read `0x0000` for every packet — a
   receiver that looks deaf. Restoring the entry **inside** the walk (count 20) brought back `0x0016`.
   The entry is `0x08 FF FF 00 00 00 00 00 00`; `0x08` is `SetDioIrqParams`, **not** junk.
3. **`lora1.fs` walked 15 of its 18 entries**, so `SetPacketParams` (preamble/CRC/IQ) and `SetDioIrqParams` never reached
   the chip while `INIT` still answered 1. Fixed (count 16, inert fillers moved out of the walked range), and **R31 now
   recognises the `TBL <ptr> ! N BEGIN` idiom** that hid it.
4. **The test suite encoded the old sync bug**: `tests/lora_spi.py` expected `0x74 0x2B` (0x74 is not an SX126x command)
   and did not expect the `0x08D8` clamp write. Corrected to the measured `0x0D 07 40 14 24` and `0x0D 08 D8 5E`.
   `tests/run.sh` is green again.
5. **Board-not-ready race** produced `refused at interpret level: 'CREATE TBL'` on perfectly good files and invalidated
   whole measurement rounds. New `tests/dev_ready.py` with `ready()` and `load_ready()` — never load into a board that
   has not answered arithmetic.
6. **Killed tests left `meshtastic --listen` children holding the serial port**, so flashes and `--set` failed with
   "Resource temporarily unavailable" and looked like dead boards. New `tests/freeports.sh` — run it before board work.

## 11. Tooling inventory (what exists now)

New or rewritten this session, all in `probe/repl/tests/`:

| file | purpose |
|---|---|
| `mesh_interop.py` | one command: probes roles by behaviour, our TX → peer RX counting real decodes, peer TX → our RX reading IRQ words, then a **named** verdict. Fails loudly (`named reason=roles`) when only one board is attached. |
| `mesh_replay_live.py` | captures one of the peer's own frames with our receiver and replays it from our transmitter — separates "their RF path" from "our frame contents". |
| `mesh_tx_freq_sweep.py` | transmit-carrier sweep with live decode attribution. |
| `mesh_power_sweep.py`, `mesh_preamble_probe.py`, `mesh_sync_tx_sweep.py`, `mesh_sync_rx_sweep.py`, `mesh_modem_probe.py`, `mesh_peer_freq_scan.py`, `mesh_peer_rx_params.py`, `mesh_peer_stats.py`, `mesh_frame_build.py`, `mesh_frame_check.py`, `make_ms_tx.py` | the individual probes from earlier sessions, still useful |
| `dev_ready.py`, `freeports.sh` | the two hygiene helpers above |
| `lint_rules_selftest.py` | mutation test for R30–R35 (6/6 firing) |

Linter gates, all green at handoff:

```bash
python3 probe/repl/tools/lintgate.py --repl examples/apps/lora/lorainit.fs examples/apps/lora/lora_rx.fs \
        examples/apps/lora/loratx.fs examples/apps/lora/lora1.fs
python3 probe/repl/tests/lint_rules_selftest.py
bash probe/repl/tests/run.sh
```

## 12. Instrument traps — read this before believing any negative

Each of these produced a *false* conclusion at least once in this session.

1. **A board can answer arithmetic and still refuse definitions.** Symptom: `refused at interpret level: 'CREATE TBL'`.
   Cause: typed in before boot finished, leaving a sticky error. Fix: `dev_ready.load_ready()` (reset, prove arithmetic,
   then load, retry the cycle).
2. **A wedged board produces long stretches of bogus negatives** and is only cured by reflashing. After any suspicious
   run, reflash our stack and re-baseline before drawing conclusions. Several sweeps in §7 predate such a reflash.
3. **`security.debug_log_api_enabled` is reset by flashing.** If it is off you will read "0 detections" from a device
   that is logging perfectly well. Always confirm with `--info | grep debugLogApiEnabled` *and* check that the capture
   file contains `message:` lines at all.
4. **A failed load still produces "preamble detected" lines.** A variant that never transmitted once produced two of
   them. Baseline every detection count against a no-transmission run (≈2 lines per 90 s here).
5. **Typed lines over 63 bytes are dropped silently** (R21). Two-byte register reads overflowed it and returned nothing —
   read one byte per command. `>BYTE`/`RD-BYTE` echoes mean you must parse output lines, not the whole reply.
6. **Reading one byte too many returns trailing garbage.** A healthy chip looked dead because every register read came
   back `0x3F` — that was the byte after the data.
7. **`GetRssiInst`, `channel_utilization` and the sign of `FEI` are all unreliable here.** `channel_utilization` reads
   `0.000000` even for the node's own traffic; `GetRssiInst` read ≈−105 dBm next to a 14 dBm transmitter.
8. **A listener and `--sendtext` cannot share a port.** Capture first, then start the listener (this ordering bug made
   one replay test report "our board never decoded a frame": the peer could not transmit while the listener held it).
9. **Meshtastic applies preset/frequency changes only after a reboot.** Setting `lora.modem_preset` and testing
   immediately measures the *old* radio configuration.
10. **Boards swap `ttyUSB*`.** Always identify by MAC.
11. `pkill -f <pattern>` matches the invoking shell; use `pkill -f "meshtast[i]c --port"`. Long board work belongs in
    `tmux`; Python needs `-u` when redirected.

## 13. Open hypotheses, ranked, with the test for each

1. **Our transmission does not reach their demodulator at usable level/quality** (most likely). Their receiver is proven
   alive, ours is proven able to hear them, and their router is proven never to receive a packet from us. The measured
   deficit is ~5 dB at equal power plus saturation above ~15 dBm.
   *Test:* an independent receiver, or the instrumented peer below, reporting the IRQ word when our frame is on air.
2. **A parameter mismatch we cannot see from our side.** Everything we can set and read back matches stock; what we cannot
   see is the *other* chip's live configuration.
   *Test:* the instrumented peer logging `RXIRQ` (see below); the first reading distinguishes "no energy" (0x0000) from
   "preamble locked but no header" (0x0004/0x0008/0x0010) from "received but CRC error" (0x0024).
3. **Their duty-cycled receive plus our preamble is marginal.** `startReceiveDutyCycleAuto(16, 8)` means their window
   must land inside our preamble.
   *Test:* very long preambles were tried (up to 1024 symbols) and failed, but several of those runs were on a degraded
   board — re-run preamble 255 and 1024 on a freshly flashed transmitter against a freshly rebooted peer.
4. **Continuous-wave sanity check.** `SetTxContinuousWave` was attempted with opcode `0xD9` and did **not** enter TX
   (`STAT` stayed `0xA2`). Get a working CW path first (correct opcode/params), then measure the peer's noise floor
   while the carrier is on — that settles "is RF leaving at all" without any protocol in the way.

The instrumented peer that would settle 1–3 is prepared, unbuilt, in `probe/results/ms-src`:
`src/mesh/RadioLibInterface.cpp` now logs `LOG_DEBUG("RXIRQ 0x%04x", irq);` at the top of `receiveDetected()`. Building
that tree is blocked on a build-toolchain packaging problem (PlatformIO from PyPI cannot drive the pioarduino platform's
current SCons), not on anything in Meshtastic or in this repo — a working build environment reproduces the observation in
one run.

## 14. Repo state

* Branch **`ulp-meshtastic`** (based on `main` merge `070c487`).
* Head commits: `acb8448` (exhaustive transmit sweep + docs N.13), `c4c71e4` (R35 + interop harness), `032bf2c`
  (link-budget control + PA fix), `72d3859`, `844b8b8`, …
* `docs/31-meshtastic-fit.md` Appendix N carries the wire facts (N.1–N.9) and this session's findings (N.10–N.13).
* `probe/results/` holds the captured frames, device logs (`*.txt`), and the extracted Meshtastic source (`ms-src/`).
  Everything there is evidence; treat the `*.txt` captures as primary sources for the numbers in §7.

## 15. How to reproduce the two headline results quickly

Receive (should pass):

```bash
./probe/repl/tests/freeports.sh
python3 - <<'PY'   # our board on the port that prints "ulp forth"
import sys, pathlib, time, subprocess
sys.path.insert(0, "probe/repl/tests"); sys.path.insert(0, "probe/repl/tools"); sys.path.insert(0, ".")
from dev_ready import load_ready
d = load_ready("<our port>", ["examples/apps/lora/lorainit.fs", "examples/apps/lora/lora_rx.fs"])
print("RADIO-INIT", d.num("RADIO-INIT .", 40.0))
for n in range(3):
    d.cmd("RC SR", 10.0, allow_error=True)
    subprocess.run(["meshtastic", "--port", "<peer port>", "--sendtext", f"hello {n}"], capture_output=True)
    t = time.time() + 12
    irq = 0
    while time.time() < t:
        irq = d.num("IQ .", 20.0)
        if irq & 2 or irq & 0x40: break
        time.sleep(0.04)
    print(f"IRQ 0x{irq:04x}")     # 0x0016 = clean decode
PY
```

Transmit (currently fails, and this is the phenomenon to explain):

```bash
./probe/repl/tests/freeports.sh
# peer device log must be on, and it must be on AFTER the last flash:
meshtastic --port <peer port> --set security.debug_log_api_enabled true
tmux new-session -d -s pl "meshtastic --port <peer port> --listen --debug > probe/results/tx.log 2>&1"
sleep 20
# our board transmits 10 frames with loratx_stocklike.fs (PA 02/02, 14 dBm, preamble 16, 869.480)
#   → then: grep -c 'hi from ulp' probe/results/tx.log      (currently 0)
#           grep -c 'message:' probe/results/tx.log         (must be > 0 or the log was not flowing)
```

---

### One-paragraph summary for the next agent

Our Forth/ULP node's receiver hears a stock Meshtastic 2.7.26 node cleanly (`0x0016`, −18 dBm) and its own frames are
byte-correct and decodable by a second board running the same firmware, but no stock node has ever decoded one of our
transmissions — across hundreds of frames, every power, preamble, carrier, PA configuration, LDRO and IQ setting, both
sync candidates, our frame, their own frame replayed, and with our firmware on either physical board. Both stock
receivers are demonstrably alive (stock↔stock works both ways), and their firmware's own log never shows a packet
reaching its router. Two real, silent bugs were found and fixed along the way (a PA configured for the wrong power band;
a table walk that left `SetDioIrqParams` unsent so the receiver reported `0x0000` for everything), each now enforced by a
mutation-tested lint rule. What remains is to observe the stock node's radio from inside — a one-line instrumentation
patch is already applied to the cached Meshtastic source; getting that tree to build and flash is the unblocking step.
