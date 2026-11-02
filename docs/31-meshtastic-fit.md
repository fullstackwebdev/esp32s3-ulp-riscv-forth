# Does the Meshtastic stack fit? — measured against this machine's budget

Source analysed, fetched **once** through `tools/fetch.py` (the repo's only network path) and cached write-once:

| | |
|---|---|
| URL | `https://codeload.github.com/Attaky-Module/meshtastic-firmware/tar.gz/HEAD` |
| cache object | `cache/objects/e70d40d3c501e959e9358fa8674dbfa9/v0001.bin` |
| bytes | **5 327 764** |
| sha256 | `a1f950a396969c1c2d256479954702debea5ebd78b97ba9b6166a9971d37454f` |
| extracted to | `external/meshtastic-firmware-HEAD/` (26 MB) |
| version | Meshtastic firmware **2.8.0** (a fork of `meshtastic/firmware`) |
| protocol source | `src/mesh/` — **24 931 lines** |

The tarball is `HEAD`, so the commit is not pinned by the URL itself; the sha256 above is the pin for what was read
here. Re-fetching appends a new `v0002.bin` and keeps this one (cache rule), so the analysis stays reproducible.

## What the stack actually puts on the wire

`src/mesh/RadioInterface.h`: `MAX_LORA_PAYLOAD_LEN 255`, `RadioBuffer` = `PacketHeader` + payload.

```
PacketHeader (16 bytes, packed):
  to            4   destination node num (0xFFFFFFFF = broadcast)
  from          4   source node num
  id            4   packet id (also the crypto nonce)
  flags         1   low 3 bits = hop_limit
  channel       1   channel hash (a hint, limits which keys are tried)
  next_hop      1   last byte of the next-hop node num
  relay_node    1   last byte of the relaying node
payload        up to 239 bytes (protobuf, then encrypted in place)
```

Channel crypto — `src/mesh/CryptoEngine.cpp`:

* key = **SHA256(PSK ‖ channel name)**, 16 or 32 bytes depending on PSK length;
* **AES-CTR**, nonce 16 B = `packetId` (8, LE) ‖ `from` (4, LE) ‖ zeros (4), counter size 4;
* the channel path has **no MIC/authentication** — integrity is the radio's CRC only;
* the PKI/direct-message path is different: Curve25519 + **AES-CCM** with an 8-byte MIC (`src/mesh/aes-ccm.cpp`,
  179 lines, reached only from `encryptCurve25519`/`decryptCurve25519`).

Radio defaults (`src/mesh/RadioInterface.h`): `bw = 125`, `sf = 9`, `cr = 5`, `preambleLength = 16`, CAD with 2
symbols, slot/CW timing for duty cycle, `MAX_TX_QUEUE 16`, `MAX_NUM_NODES 120` on ESP32-class targets.

**Note for anyone comparing with our driver:** our Forth driver is SF9 / BW125 / CR 4-5 / preamble **8** at 868.1 MHz.
The preset matches; the preamble length does not (8 vs 16). A Meshtastic node matches preamble by correlation, so
8 vs 16 is not fatal, but it is a difference to be aware of, measured in `src` rather than assumed.

## The budget it has to fit in (all measured on this repo)

| budget | value | how |
|---|---|---|
| ULP region − stack reserve | 8 192 − 260 = **7 932 B** | `docs/30-budget-ledger.md` |
| ULP image | **7 931 B — 1 B free** | `riscv32-esp-elf-size` |
| Forth pool `MEMSZ` | **2 566 B** (resident baked 2 438) | `uforth -d` |
| free at boot prompt | **1 328 B** | board: `HERE 786`, `LATEST 2114` |
| radio driver alone (`lora1.fs`) | **1 028 B** | board: `HERE 786 → 1814` |
| driver + receive words | **1 186 B**, leaves **61 B** | board: `HERE 1 972`, `LATEST 2 033` |
| one phase window | **999 B** | board: `resident sealed; phase window 999 B` |

## Verdict 1 — phases cannot host this, and cannot even host our driver

The phase window is **999 B**; the radio driver alone is **1 028 B**. A phase therefore cannot contain the driver,
let alone driver + anything else. Chains buy *sequence* (many programs of ≤999 B, sharing state through the sealed
registry), not *space*: each phase re-declares the words it uses, because a phase cannot see another phase's
definitions (measured earlier this era: a phase using another phase's `DRAW` is refused by name).

## Verdict 2 — an interoperable Forth sender does not fit either

Minimum to be decoded by a real Meshtastic node as a text message:

| piece | size | basis |
|---|---|---|
| radio driver (as we have it) | 1 028 B | measured |
| AES-128 block + CTR (S-box + key schedule + counter loop) | ~450–600 B | derived: 256 B S-box table + ~200–350 B of Forth |
| minimal protobuf `Data{portnum=TEXT, payload}` encode | ~120–200 B | derived: varint + length-delimited writer |
| 16-byte header build + packet-id counter + node num | ~60–100 B | derived |
| **total** | **≈ 1 660–1 930 B** | against **1 328 B** free at the prompt |

So the shortfall is ~25–45 % of the entire pool, and the image has **1 B** of headroom, which forbids growing
`MEMSZ` (every pool byte costs an image byte). Shrinking the kernel by ~600 B is the only way to make room, and the
kernel is the thing that gives us the REPL, the store, the phases and the App Store.

One thing that *would* fit, and is worth knowing: **SHA256 key derivation can be done once, in its own phase**, with
the resulting 32-byte key stored in `examples/apps/registry.fs` below the seal. That removes ~300 B from the frame
path. It does not change the verdict, because AES-CTR is still resident for every packet.

## The three architectures this leaves

**A. Restore Meshtastic (the board's own firmware).** Full 2.8.0 device: encryption, ACKs, routing, node DB, BLE,
presets, duty cycle. The backup already exists
(`backup/heltec-v3-meshtastic-xxxxxxxxxxxx-8MB-20261101-1653.bin`, restore verified). Cost: the ULP owns nothing,
and the HP core runs the stack. This is the only option that interoperates *today*.

**B. ULP radio server + Meshtastic on the HP core.** Keep what this era proved — the coprocessor owns every SPI edge
and can transmit with the HP core asleep — and give the stack a mailbox instead of RadioLib's SPI. The choke point is
narrow and identifiable: `src/mesh/RadioLibInterface.cpp` (799 lines) and `SX126xInterface.cpp` (527) are the only
places that touch the chip, behind `RadioInterface`'s API (`send`, `startReceive`, `getPacketTime`, RSSI/SNR). A ULP
mailbox ("send these bytes" / "here are the bytes, with the radio's RSSI/SNR") is a realistic port target: the stack
keeps protobuf, AES, routing and node DB on the HP core where the RAM is; the ULP keeps the timing and the sleep.
Cost: a real project — two new interface classes plus an RPC, and every radio API call has to become asynchronous.

**C. Our own Forth protocol (what is on the boards now).** 4-byte frames, no crypto, no addressing. Works, measured
both directions, and is the right thing for ULP-level work — but nothing else on 868 MHz can read it.

## What we turned off to get here, for the record

Kernel: no `DO`/`LOOP`, no `>`, `0>`, `0<`, `MOD`, `ABS`, `MIN`, `MAX`; no `>R`…`R>` across a typed line; a
definition must fit one 92 B block; a typed line must stay under the 63 B ring; no cross-line `IF`/`ELSE`; `\`
comments illegal in block sources. Build: `-Os`, `-DULP_EARLY=0`, `-DFOREIGN_ULP=0`, `-DULP_HAL=0`,
`-DENGINE_TEST=0`. Driver: frequency/SF/BW/CR/preamble/header/CRC all pinned at compile time, payload fixed at
**4 bytes**, DIO1 unused (200 ms air-time wait instead of the IRQ line), no CAD/LBT, no hopping, no sync-word change,
no queue, no power control, SPI bit-banged at ~144 kHz (≈970 cycles/byte, measured on the C ULP driver).
