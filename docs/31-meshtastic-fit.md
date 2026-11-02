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

## Appendix C — INIT is now a phase, and it is verified (measured)

`examples/apps/lora/lorainit.fs` is the bring-up as a chained job: its own primitives, the radio configuration as a
**byte table**, and `RADIO-INIT`/`STAT`/`PTYPE` as its entry points. Measured footprint on the board: **code 710 B +
headers 69 B = 779 B**, self-contained, leaving 549 B free - it fits a 999 B phase window with room to spare.
`tests/lora_init_phase.py` proves it (7/7 checks): `RADIO-INIT → 1`, chipmode `STDBY_RC`, `GetPacketType → 1` (LoRa),
`SR → chipmode 5` (RX), and a frame from the **app-phase** radio on the other board decodes with its exact marker
`[165, 49, 50, 51]`.

Why a phase is the right home for it: as Forth code in the app it cost **491 B of the app's 1 328 B**; as a phase it
costs the app nothing, because the pool is rewound at each hop. The app-side set becomes primitives (382) + `SEND`
(127) + receive words (~266) ≈ **775 B**, which leaves ~550 B of the same budget for AES-CTR and the protobuf writer -
the difference between "impossible" and "tight but real".

Three bugs this phase found, all of them silent, all now gated:

| bug | how it presented | gate |
|---|---|---|
| table length bytes one too high (`3 C, 128 C, 0 C,` for a 2-byte command) | every command after the first was garbage: the radio stayed in standby, `SetRx` did nothing, the receiver looked dead, yet `RADIO-INIT` still answered 1 (SetStandby with a junk parameter is still SetStandby) | the table's lengths are now checked against the bytes that follow them, and the test asserts `PTYPE`/chipmode/RX rather than the return code |
| an odd `C,` count leaves `HERE` odd | the next eleven definitions answered `ERR_DICT` with 848 B still free - an error that names the dictionary for a fault that is alignment | **lint R28** (parity of interpret-state `C,`) |
| `Dev.reset()` shelled out to `esptool --after hard_reset` | esptool 5.x rejects that spelling, the error was captured and discarded, the readiness probe then succeeded on the *already running* board, so no reset ever happened and tests read the previous session's dictionary (a phase was accused of defining `SR`; a resident-name collision appeared from nowhere) | `reset()` uses `hard-reset` and now **asserts the dictionary is fresh** (`HERE` must be the baked 786, not a leftover) |

Two measurement corrections in the same pass, both from trusting a byte I had not verified:

* a register readback of the frequency at `0x0880` was asserted as "868.1 MHz" while the offset itself was a guess
  (it answered `3 0 0 95`). It was replaced by `GetPacketType`, a documented command: `1` = LoRa.
* `RL` read GetRxBufferStatus as two bytes, so the **status** byte became the payload length and `RB` dumped 208
  bytes instead of 4. The marker was at the front of the dump, which would have passed a sloppier check.

## Appendix D — AES measured, and the answer to "how much app space"

Written and measured on the board this session (`examples/apps/lora/lora_aes.fs`, `lora_keysched.fs`), FIPS-197 tables,
byte-wise Forth with no `DO/LOOP` and no structure spanning a typed line.

| file | code | headers | **total** | fits? |
|---|---:|---:|---:|---|
| `lora_keysched.fs` (S-box + RCON + W + schedule) | 774 B | 51 B | **825 B** | yes — a 999 B window with 174 B spare |
| `lora_aes.fs` (S-box + W + block + CTR) | 1 230 B | 114 B | **1 344 B** | **no** — 16 B over the whole 1 328 B prompt, and 345 B over a phase window |

So the honest answer to "how much app space do we need": the cipher alone is **~1.3 KB**, on top of the radio's
1 186 B and the frame encoder. Nothing about that is close.

What the split bought, and what it did not:

* the key schedule is **825 B and separate**, so a chain can run it once per channel and never carry it again;
* the block+CTR unit still needs **1 344 B**, which does not fit a 999 B phase, so `AES` cannot be one phase at its
  current size. The three ways out, in order of value:
  1. **compute the S-box instead of tabulating it** — the table is 256 B of the 1 344 B; a GF(2^8) inverse plus the
     affine map replaces it with code, and the round keys (176 B) stay because they are per-channel data;
  2. **one round per phase** — state (`ST`, `W`, `NONC`, the round counter) lives in the sealed registry, so a
     `AES-ROUND` phase does SubBytes+ShiftRows+MixColumns+AddRoundKey and chains to itself; 11 hops at the measured
     4.5 ms per adopt is ~50 ms against an air time of ~180 ms at SF9;
  3. **grow the window**, which means growing `MEMSZ`, which costs image bytes 1:1 — and the image has 1 B free. The
     only source is the interpreter itself (`vm_enter` = 2 104 B of the 7 931 B image, measured with `nm`).
* both files pass `tools/lint_forth.py` (R21/R22/R28/R2/R3/R4) and `tools/namecheck.py` against the board.

Three linter gaps this work exposed, all fixed:

* **`collect_vocab` read a colon inside a comment as a definition opener.** `\ BUDGET: this driver needs MEMSZ >= 2550`
  made the `--use` vocabulary capture `this` and swallow the real definitions up to the next `;`, so `RD-BYTE` and `RD2`
  were invisible and a dependent file was refused for using them. It is a token scan now, with a selftest fixture.
* **a declaration was borrowed from a later definition.** Reading 120 characters of tail gave `NSSLO` (which takes
  nothing) an input, so five words that call it reported underflow. The declaration must now follow the name
  immediately.
* **R4 found a real bug in the shift-rows body** — a spurious `A @` at the head, which would have leaked a stack item
  per round while producing plausible-looking output. That is the clearest argument for making the linter a gate.

**The gate itself:** `probe/repl/tools/lintgate.py` wraps the linter in both modes, refuses on ANY finding, and takes
`--after prior.fs` for files that are only checkable in context (the receive words need the driver's `NSSLO`). It is
called by every hardware test and by `tests/run.sh`, and `AGENTS.md` states the rule in one line.

## Appendix E — the cipher runs on the chip, and the S-box question is settled

**AES-128 in Forth, on the ULP-RISC-V, matches openssl.** `tests/lora_aes.py`, 9/9 twice:

```
PASS  cipher loads with no refused line
PASS  cipher fits the prompt dictionary           1328 B used, 0 B free
PASS  AESB / ARK / MC / SR exist after the load
PASS  plaintext is in ST                          00112233445566778899aabbccddeeff
PASS  AES-128 block matches openssl               69c4e0d86a7b0430d8cdb78070b4c55a
```

The expectation is generated, never remembered: `tools/gen_aes_vectors.py` validates the key schedule
against the **published** FIPS-197 A.1 expansion (`a0fafe17 88542cb1 23a33939 2a6c7605`) and takes the
ciphertext from `openssl enc -aes-128-ecb`. Recalled values were wrong twice in one session — `a0fafe17`
belongs to FIPS-197's *other* example key (`2b7e1516…`), and this key's `w4` is `d6aa74fd`.

### "Compute the S-box instead of tabulating it" — measured, and it loses

| | table | computed (GF(2^8) inverse + affine) |
|---|---:|---:|
| dictionary | **256 B** | 644 B (590 code + 54 headers) |
| time for one SubBytes (16 bytes) | ~0 | **2 274 ms** (142 ms per byte, measured: 256 evaluations in 36.4 s) |
| time for one block (10 rounds) | ~0 | **≈ 22.7 s** |

The computed S-box is **correct** — all 256 values, sum 32 640, identical to the field definition — and it is
388 B larger and 22.7 s per block against 180 ms of air time. The table stays. That lever is closed with
numbers rather than an opinion.

### Where the cipher stands against the two windows

| | measured |
|---|---|
| `lora_aes.fs` (S-box 256, W 176, ST 16, TZ 16, cells 8, code) | **1 328 B** — fills the prompt exactly, 0 B free |
| a phase window | 999 B — so the cipher **cannot be a phase** as it stands, short by ~329 B |
| `lora_ctr.fs` (BUF, NONC, LEN, XOR layer) | **37 B** of words — separate, because the cipher had no room left |

The remaining levers for a phase, in value order: W (176 B) into the sealed registry, since round keys are
per-channel data that outlive the phase; then the 16 `C,`-free buffers if the registry can hold them too.
`RNDS`/`MCS`/`MCSB` are already single-use-inlined.

### Six failures this work produced, and the gate each one now has

1. **`ERR_DICT` at a definition that is not short of space.** Four 1-byte cells summed to an even 4 bytes,
   so the *total* parity check passed, while `HERE` was odd at every intermediate `CREATE` — and the engine
   checks parity at **every** `mkentry`. Forty definitions were refused. **R28 now checks parity at each
   definition head**, with a fixture whose total is even.
2. **A definition that answers `ok` and does not exist.** With 0 B free, `: FIN … ;` was accepted, left a
   dangling header, and `FIN` was not findable afterwards (`' FIN` → `FIN?`). The load reported no error.
   The test now asks the board for every word it needs.
3. **A 32-bit store of a big decimal is not the number you wrote.** `2291784379` (0x8899AABB) came back as
   `-77665545`. Bytes go in with `C!` now.
4. **A helper definition that costs more than the room left.** Two helpers in the vector file cost 20 B
   against 12 B free → `ERR_DICT`, `ST` stayed zero, and the comparison "failed" for a reason that had
   nothing to do with AES. The vector file now defines nothing (`v o W + C!`).
5. **R23 called a key word a register.** It treated every literal ≥ 0x10000 as an address, so 22 round-key
   stores were reported as narrow register access. It is limited to the two real ranges (0x6000_0000..
   0x6003_FFFF and the alias window 0xA400..0xD3FF), and the selftest gained **negative fixtures** (a case
   that must produce NO finding), because a rule that flags valid code gets switched off.
6. **`collect_vocab` opened a definition on a colon inside a comment** and borrowed stack effects from a
   later definition — both made `--use` quietly weaker. Fixed earlier this session with fixtures.

Every one of these was caught by the linter or by the board, not by reading the source.

## Appendix F — a Meshtastic-shaped frame leaves the chip, sent by ONE phase

`examples/apps/lora/loratx.fs` is **939 B measured** (code 858 + headers 81), i.e. it fits the **999 B** store
window with 60 B spare, and it does the whole job by itself: pad primitives, the 14-entry config table from one
byte table, `WriteBuffer`, `SetTx`, and a polled TxDone. `tests/lora_frame_phase.py`, 10/10 twice:

```
PASS  receiver RADIO-INIT configures the chip
PASS  receiver is in RX mode                       chipmode 5 (5 = RX)
PASS  TX phase fits the store window               939 B of 999 B
PASS  RUNLORA returns to STDBY_RC                  status 0x2c
PASS  TxDone is set after the send                 IRQ 0x0001
PASS  receiver reports RxDone                      IRQ 0x0016
PASS  frame length on the air                      26 B at offset 0
PASS  header bytes match the Meshtastic layout     ff ff ff ff 0a 0a 0a 0a ca fe 00 01 00 00 00 00
PASS  protobuf Data{portnum,payload} matches       08 80 02 12 05 68 65 6c 6c 6f
```

`ff ff ff ff` broadcast · `0a 0a 0a 0a` from · `ca fe 00 01` packet id · flags 0 · channel 0 · next_hop 0 ·
relay 0, then `08 80 02` (portnum 256 = PRIVATE_APP), `12 05`, "hello". Decoded from the **receiver's own RX
buffer**, not from the sender's intent.

**It is not yet Meshtastic-readable, and the reason is arithmetic, not effort.** Meshtastic's channel path is
AES-CTR, and the cipher is **1 328 B** — it fills the whole prompt dictionary exactly (0 B free) and a phase
window is 999 B, so the cipher cannot be a phase. Moving its data is blocked too: registry cells are
**resident** (`cli.py:registry_cells`, "every cell costs 4 B of the window") and the image has **1 B** free.
The frame above names exactly where the ciphertext goes: the Data payload region, bytes 18..21.

What *is* proven about the cipher, on the chip: the AES-128 block matches `openssl enc -aes-128-ecb`
(`69c4e0d86a7b0430d8cdb78070b4c55a`), and the CTR **keystream** matches `openssl enc -aes-128-ctr`
(`c6a13b37878f5b826f4f8162a1c8d879`). So Meshtastic interoperability is now a *size* problem with a known
solution shape, not an unknown.

### Four failures this phase produced, and the gate each one now has

1. **R29 (new).** A control structure must be COMPLETE on the typed line. `SND`'s loop was split across two
   lines and answered `ERR_STACK` with **488 B free** — the failure read as "no space" and was not. R29 now
   refuses any line whose `IF/THEN` or `BEGIN/WHILE/UNTIL/REPEAT` do not balance, with a fixture for the split
   case and a negative fixture for the valid one-line loop.
2. **`code_only` did the `( ... )` pass BEFORE stripping `\` comments.** A `(` inside a comment opened a
   "declaration" that blanked real code up to the first `)` far away; the prose that survived counted as words,
   and R29 refused `lora1.fs` for a `then` in the sentence "… a bare `1 MOSIPAD PIN!` then moves OUT to". Every
   token-based rule (R16, R23, R26, R29) reads through this function, so the order is the whole point.
3. **`scan_lines` dropped comment-only lines**, so indices were shorter than the source and a finding could be
   attributed to a line that does not exist. R29 numbers against the source's own lines now.
4. **Packet params are shared by TX and RX.** Setting the receiver's payload length to 26 for this frame also
   set the *transmitter's*, and `SEND` — which sleeps a fixed 200 ms and then reads TxDone — returned 0 while
   three 26-byte frames crossed the air. Measured three ways:

   | receiver params | result |
   |---|---|
   | preamble 8 / length 4 (the driver's INIT) | deaf to a 26-byte frame: `IRQ 0x0000` |
   | preamble 16 / length 255 | deaf too: `IRQ 0x0000` |
   | preamble 16 / length 26 (the frame's own) | `IRQ 0x0016`, 26 bytes decoded |

   So the receive length must name the frame, the params belong to the *scenario* rather than to `SR`, and a
   length change must be paired with a transmitter that waits for TxDone instead of sleeping.

## Appendix G — where each piece fits, measured after the table-driven INIT

The driver's configuration stopped being 491 B of hard-coded code and became a **70 B table** plus five short
words, generated from the old body so the wire is unchanged (`INIT` -> 1, two-board PASS both directions).
That changed every number below:

| piece | measured | window | fits |
|---|---:|---:|---|
| driver (`lora1.fs`, table-driven INIT + `SEND`) | **855 B** | prompt 1 328 B | yes |
| receive words (`lora_rx.fs`: `SR` `RC` `IQ` `RL` `RDUMP` `RB` `RXTAKE` `RX1` `RPP`) | **322 B** | — | — |
| driver + receive words, together, in the PROMPT | **1 177 B** | 1 328 B | **yes, 151 B spare** |
| `lorainit.fs` + `lora_rx.fs` as one PHASE | **1 023 B** | 999 B | no, **24 B over** |
| frame + TX phase (`loratx.fs`) | **939 B** | 999 B | yes, 60 B spare |
| cipher (`lora_aes.fs`) | **1 328 B** | 999 B | no, **329 B over** |

So today's device shape is: the radio lives in the prompt (proven by `lora_two_board.py`, 3+3 frames), the
26-byte frame and its transmission live in a phase, and the cipher is the one item with no home. The receive
bundle *would* fit a phase 24 B short of where it is, so a "receive as a phase" design needs 24 B of app space,
not a redesign.

`RPP` and `RX1` are **back** in `lora_rx.fs`. They were removed earlier in the session to make the numbers fit,
which is the wrong trade — a feature is not slack — and the driver's table paid for them instead.

### Where the remaining app space could come from

Read out of the built ULP binary (`riscv32-esp-elf-size` and `nm` on `build/esp-idf/main/ulp_main/ulp_main.elf`):

```
   text    data     bss     dec
   4834    2584     513    7931          budget 7932, so 1 B free

   2104 t vm_enter        <- 26% of the image, the outer interpreter loop
    534 T main
    314 t word
    302 t interpret
    210 t mkhdr
    142 t blk_xfer
    142 r disp_tbl
    116 t find
   2566 d mem            <- the dictionary itself (MEMSZ)
```

`mem` is `.data`, so **+1 B of app space costs exactly 1 B of image**. The cipher's 329 B, the receive phase's
24 B and the Meshtastic payload growth all draw on the same 1 B. Nothing in the cipher is redundant: the S-box
table is the compact form (computed = 644 B and 22.7 s per block, Appendix E) and the round keys cannot move to
the registry (cells are resident, Appendix F).

### The candidate list for that space, and the method to price one

27 of **231** resident names are never named by the App Store corpus, the tests, the tools or the prelude. That
is a raw list, not a removal list — several are runtime primitives the compiler emits (`LIT`, `LIT2`, `(DO)`,
`(LOOP)`, `(+LOOP)`, `(.")`) or engine state the interpreter reads (`Q`, `QH`, `QT`, `QOVF`, `VS`, `BH`,
`CURBLK`, `OVLRUN`, `BL`):

```
LIT (DO) (LOOP) (+LOOP) UNLOOP U/MOD (.") GPIO@ GPIO! ADC@ WAKE LIT2 VS BH BL OVLRUN CURBLK Q QH QT QOVF
BRT EV@ PUMP 324, 1272 2510,
```

Priced one at a time: delete the name, rebuild, `riscv32-esp-elf-size` for the image, `HERE`/`LATEST` on the
board for the dictionary, raise `MEMSZ` by exactly the bytes freed, then re-run suite (30), linter selftest,
`lora_spi`, `lora_two_board`, `lora_init_phase`, `lora_aes`, `lora_frame_phase`. A name absent from the corpus
can still be emitted by the compiler, which is why this is a candidate list and not a plan.

### Two dead ends already priced (do not retry these)

* **computed S-box**: correct for all 256 values, 644 B and 22.7 s per block against a 256 B table. Appendix E.
* **registry for round keys**: cells are RESIDENT (`cli.py:registry_cells`, "every cell costs 4 B of the
  window"), so moving 176 B of `W` there shrinks the window by as much as it saves. Appendix F.
