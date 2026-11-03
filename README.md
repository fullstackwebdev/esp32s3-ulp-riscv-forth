# Forth on the ESP32-S3 ULP-RISC-V coprocessor

A Forth system that runs on the ESP32-S3's ULP-RISC-V coprocessor: interpreter, compiler, dictionary,
console, block-store client and a phase dispatcher for programs built as chained images. The ESP32-S3's
main cores move bytes and serve blocks; they never execute a token of Forth.

## The chip

| | |
| --- | --- |
| Coprocessor | ULP-RISC-V, ESP32-S3 (TRM §2.6.1) |
| ISA | `-march=rv32imc_zicsr_zifencei -mdiv`, 32 GPRs, hardware multiply and divide, ILP32 soft-float |
| Memory | **8 176 B** RTC slow RAM; static pool limit **7 932 B** (8192 − 261 B C-stack reserve above it) |
| Clock | RTC slow clock measured **154.9 kHz ± 0.5** (the vendored docs say 136 kHz, ~12 % wrong for this part) |
| Host link | UART bridge on the main core; the ULP cannot touch flash, PSRAM or the UART directly |

That compiler line is the boundary: code outside it does not assemble.

## What runs where

The main core embeds a 7 424 B ULP image, starts a byte pump between UART and two rings, and starts a
block server. Every token is interpreted on the ULP. A typed line goes through the pump, wakes the coprocessor, and the
answer comes back the same way.

RAM on the ULP is one array (`mem[]`, `MEMSZ` 2 566) split three ways: compiled code growing up from
`DICT`, a fixed-stride header table growing down from the block window, and the 128 B block window at the
top. Each region is bounds-checked before a write.

## Capabilities

- **Interpret and compile from a terminal.** Definitions, `IF/ELSE/THEN`, `BEGIN/UNTIL/WHILE/REPEAT`,
  `DO..LOOP`, `CREATE`, `CONSTANT`, recursion, case-insensitive lookup, backspace, `ok`.
- **Hashed dictionary, no names, no links.** 4-byte headers: `hash20 | xt11 | imm1`, fixed stride, so a
  lookup is one hash and one scan. `' NAME .` prints the xt, or names the miss (`' SPAWN .` → `SPAWN?`).
- **Durable blocks.** 128 B blocks in a raw `esp_partition`, `BLK1` superblock with generation and CRC,
  32 blocks per 4 KB sector. A block operation writes a mailbox, rings a doorbell, and the main core
  copies both ways, summing checksums and writing status last.
- **Programs as phases chained through the store.** A phase is one built image sized to the window above
  the seal; a program is a chain of phases. A 24-hop chain has been run end to end, hops at ~2.1 ms.
- **Named failures.** `ERR_STACK`, `ERR_DICT`, `ERR_DIRTY`, `ERR_RANGE`, `ERR_CRC`, `ERR_BUFOVER`,
  `ERR_BUSY`, `ERR_NOSERVER`, `ERR_ULPCODE`, `ERR_TASKS`, `ERR_UNNAMED`.

## Examples

Measured on the flashed build (`' X .` yields an xt or names the miss):

```
2 3 + .               -> 5 ok          (arithmetic; the answer comes back through the pump)
: SQ DUP * ;          -> ok
7 SQ .                -> 49 ok         (compiled at runtime, on the coprocessor)
: FIB DUP 2 < IF ELSE DUP 1- FIB SWAP 2 - FIB + THEN ;
10 FIB .              -> 55 ok
15 FIB .              -> ERR_STACK     (1 cell per level, 16 refused by name)

0 BLOCK .             -> 2438 ok       (address of the 128 B block window)
65 0 BLOCK C!         -> ok
SAVE .                -> 0 ok          (checksummed write into the flash partition)
0 BLOCK C@ .          -> 65 ok         (read back, checksummed the other way)

' SEAL .              -> 446 ok        ' BLOCK . -> 3962 ok    ' LOAD . -> 3954 ok
' SPAWN .             -> SPAWN?        (task machinery is not in this image)
```

A program is not typed in: `cli.py` builds each phase through the store and hands the launcher the first
descriptor.

## Programs are phases

- A **phase** is one built image, laid through the store at a descriptor, sized to fit the window above
  the seal. It cannot be larger than the window, so it always fits.
- A **program** is a **chain** of phases. Each phase ends by executing `CHAIN <descriptor>`; the successor
  is a literal in the phase source and the descriptor map lives in `cli.py`'s `LIBRARY`, with a check that
  the literal matches the next phase. Descriptor `0` ends the chain and is also the dispatcher's stop
  value, so a chain cannot run past its end.
- **Phases reuse memory; they do not add it.** A phase is swapped in over the previous one, and cannot call
  another phase's words, so the primitive set stays resident and each phase re-declares what it needs.
  Each declares its scratch with `\ SCRATCH: NAME`, one per line, which the linter enforces.

The worked example is AES-128-CTR: 1 328 B of working state against a 999 B window, so the cipher is six
phases and the state is handed over in the SX1262's own 256 B buffer.

| phase | descriptor | size | work |
| --- | --- | --- | --- |
| `aesseed` | 80 | 663 B | radio config, nonce, round 0 |
| `aessub` | 88 | 836 B | SubBytes |
| `aessr` | 96 | 722 B | ShiftRows |
| `aesmc` | 104 | 985 B | MixColumns |
| `aesark` | 112 | 898 B | AddRoundKey, round counter, chains back while round < 11 |
| `aesout` | 72 | 804 B | encrypt, frame, transmit |

## Sizes and limits

| | |
| --- | --- |
| ULP image | **7 424 B** (`ulp_main.bin`; the boot banner prints it) |
| ELF sections | text 4 834 + data 2 584 + bss 513 = **7 931 B** |
| Budget | **7 931 / 7 932 B** (`flash_safe.sh` refuses over it; an 8 027 B image does not boot) |
| `MEMSZ` | 2 566 (the dictionary and block window live in `.data`) |
| App space at the prompt | **1 328 B** — `LATEST 2114 − HERE 786`, measured on this image; it was **690 B** before the reclaim (+763 B measured then, docs/23) |
| Phase window | **999 B** at this `MEMSZ`; **1 193 B** with the dispatcher-only launcher |
| Recursion | depth 15, 16 refused with `ERR_STACK` |
| Concurrency | one block request in flight; a wedged request holds the layer until reset |
| Not present | tasks (`SPAWN` is source-only here), `WORDS`, `SEE`, floating point |

Multi-tasking existed and was removed from the shipping image on purpose: its bytes became app space.

## Repository layout

| path | contents |
| --- | --- |
| `probe/repl/` | the shipping image: `src/` engine + ULP harness, `main/` bridge, `tests/`, `tools/` |
| `probe/results/` | per-probe results and kept evidence |
| `examples/apps/` | Forth applications, including the LoRa tables |
| `cli.py` | store driver: `--library` builds the launcher and the phase library |
| `docs/` | design, measurements, journal; index at `docs/00-index.md` |

## Build and run

```sh
export IDF_PATH=/path/to/esp-idf && . "$IDF_PATH/export.sh"   # ESP-IDF v5.4
cd probe/repl && idf.py -p /dev/ttyUSB0 -b 460800 flash      # 3 × "Hash of data verified"
```

```sh
./cli.py --library                     # build the launcher + phases through the store
bash probe/repl/tests/run.sh           # host suite and board gates
python3 probe/repl/tools/lintgate.py --repl examples/apps/lora/lorainit.fs   # table gate
python3 probe/repl/tests/lint_rules_selftest.py                             # the gate's own mutation tests
```

Long builds go in `tmux` with `nice`, not the foreground.

## LoRa

An SX1262 driver, a receive path and AES-128-CTR are written in Forth and run on the ULP; the radio fits in
two phases (992 B receive, 939 B transmit). Frames are byte-identical to Meshtastic's own encoding, and a
stock Meshtastic 2.7.26 node is decoded by this stack (`IRQ 0x0016`, −18 dBm). The transmit direction into a
stock node is unsolved: `docs/32-handoff-meshtastic-interop.md` records every experiment and the current
state. Wire facts are in `docs/31-meshtastic-fit.md` (Appendix N).

## Licence

MIT for this repository's code and prose (`LICENSE`); third-party material keeps its own licence and is not
vendored. See `NOTICE.md` and `docs/SHARING.md`.
