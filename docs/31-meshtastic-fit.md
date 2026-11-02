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

## Appendix A — app space needed, built from MEASURED word sizes

Per-word cost on the board (each definition typed separately, `HERE`/`LATEST` deltas, `MEMSZ` 2 566, boot free 1 328):

| word | code | hdr | total | role |
|---|---:|---:|---:|---|
| `PIN!` | 38 | 3 | 41 | primitive |
| `PIN@` | 30 | 3 | 33 | primitive |
| `BITOUT` | 58 | 3 | 61 | primitive |
| `>BYTE` | 22 | 3 | 25 | primitive |
| `BUSY-LOW` | 34 | 3 | 37 | primitive |
| `NSSLO` | 14 | 3 | 17 | primitive |
| `NSSHI` | 12 | 3 | 15 | primitive |
| `BITREAD` | 42 | 3 | 45 | primitive |
| `CLOCKLOW` | 28 | 3 | 31 | primitive |
| `RD-BYTE` | 24 | 3 | 27 | primitive |
| `RD2` | 16 | 3 | 19 | primitive |
| `INEN` | 28 | 3 | 31 | primitive |
| **primitives total** | | | **382** | needed by everything |
| `INIT` | 488 | 3 | **491** | radio config: 45 command bytes written as code |
| `SEND` | 124 | 3 | **127** | transmit |
| RX words (`SR RC IQ RL RDUMP RB RXTAKE RX1`) | 198 | 24 | **222** | receive |

So the radio end of the stack is **1 222 B** of app space today, and it works (measured, both directions).

To carry a **Meshtastic-decodable** frame, add (derived from the source read above, priced against the table):

| piece | bytes | basis |
|---|---:|---|
| AES-128 CTR: S-box table 256 + round keys 176 + code ~250 | **~680** | derived; encryption is needed per packet, so it is resident for the whole session |
| protobuf `Data{portnum, payload}` encode (varint + length-delimited) | **~160** | derived |
| 16-byte `PacketHeader` build + packet-id counter + node num + channel hash | **~80** | derived |
| **TX-only, interoperable** | **~2 140** (1 222 + 918) | sum |
| table-driven `INIT` instead of 491 B of code: ~100 B code + ~50 B table | **−390** | measured 491, derived replacement |
| **TX-only, interoperable, compacted** | **≈ 1 750** | sum |
| + RX decrypt + protobuf parse (reuses the AES phase) | **+~300** | measured RX 222 + derived |
| + ACK/retry, dedupe ring, duty-cycle accounting | **+400…800** | derived |

**Answer to "how much app space":** **≈ 1 750 B for a transmit-only device that a Meshtastic node can read,
≈ 2 050 B for both directions, ≈ 2 450–2 850 B for something usable as a device.** Today the machine gives
**1 328 B** at the prompt and 61 B spare once the current driver is loaded, so the gap is **+450 to +1 500 B**.

Every byte of that gap has to come out of the 8 KB region, because the image is at 7 931 / 7 932 B:

| lever | size | how it was measured |
|---|---|---|
| interpreter text (`rsicv32-esp-elf-nm --size-sort`) | `vm_enter` **2 104 B**, `main` 534, `word` 314, `interpret` 302, `mkhdr` 210, `blk_xfer` 142 — text **4 834 B** total | measured on the built ELF |
| pool `mem` | **2 566 B** in `.data` — so freeing 1 text byte buys exactly 1 pool byte | measured (symbol `mem` = 2566) |
| baked prelude inside the pool | **2 438 B** (from `uforth -d`); the per-word split is the next thing to measure | measured total |
| ULP stack reserve | **260 B, at 0 B free** (high-water 244/244) — cannot be a source | measured by the board's own stack report |

So the levers, in order of value: **(1)** `vm_enter` is 27 % of the whole image — a simpler inner interpreter is the
only large single win; **(2)** trim the 2 438 B baked prelude; **(3)** ship a radio-target image without the block
store and its server path when the radio app is what runs; **(4)** the table-driven `INIT` above, which is the one
lever that is *app-side* and does not touch the engine.

## Appendix B — the chained-phase strategy, and what it costs

Chaining works, and with more app space it becomes *simpler*, because the tax that makes it expensive today is
removable: **every phase pays for the words it uses, since a phase cannot see another phase's definitions**
(measured: a phase calling another phase's `DRAW` is refused by name). Today that tax is the **382 B** primitive set,
re-declared in each phase.

The structure that removes it:

1. **Resident layer (baked into the image, callable from every phase):** the pad/SPI primitives — 382 B measured,
   plus `>BYTE`/`RD-BYTE`/`NSSLO`/`NSSHI`/`BUSY-LOW`/`INEN`. Cost paid once; each phase then costs only its own job.
2. **Phases, each one job, each ≤ 999 B window:**

| phase | job | budget |
|---|---|---:|
| `RADIO-INIT` | table-driven config (~50 B table + loop) | ~100 B |
| `FRAME` | 16-byte header + protobuf `Data` encode | ~200 B |
| `AES` | AES-128 CTR, encrypt and decrypt (same routine) | ~600 B |
| `TX` | `WriteBuffer` + `SetTx` + `TxDone` from `GetIrqStatus` | 127 B measured |
| `RX` | continuous `SetRx`, `RxDone`, `ReadBuffer` | 222 B measured |
| `ACK` | counter/retry/hop state machine | ~200 B |

3. **State lives in `examples/apps/registry.fs`, below the seal** — packet id, node number, channel hash, retry
   counter, dedupe ring, and the 32-byte channel key. It survives the hop; it also *costs pool bytes* like everything
   else, so a 256 B S-box and 176 B of round keys live in the same budget.
4. Rules that do **not** go away with more app space: one definition per 92 B interpret-state boundary, typed lines
   under 63 B, no cross-line `IF`/`ELSE`, no `DO`/`LOOP`, descriptors on an 8-block stride, and a phase hop costs
   **4.5 ms** (measured: 4.5 of the 5.1 ms a hop costs, `repl_main.c`).
5. **Performance is not the constraint — memory is.** AES-128 CTR over a ~66 B packet is ~5 blocks × 10 rounds;
   at the ULP's 17.5 MHz (measured cycle counter) with this token-threaded engine that is a few tens of ms, against
   an air time of ~180 ms at SF9/BW125 for that size. The radio dominates; the cipher fits in the gaps.
