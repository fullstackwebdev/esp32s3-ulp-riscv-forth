# An interpreted, block-storage, phase-chaining Forth in eight kilobytes, with 11 bytes to spare.

**What it is.** A Forth machine that lives entirely inside the ESP32-S3's 8 KB coprocessor. You type
Forth at a serial console; the ULP interprets and compiles it on-chip, runs it, loads and chains built
program *phases* through a flash-backed store, and reads and writes durable blocks — the main core is a byte
pump that never executes a single token of Forth.

The whole machine — interpreter, dictionary, console ring, block client, phase dispatcher, error paths —
is **7 845 of 7 856 bytes**. It also *had* multi-tasking; that is what the reclaim spent (below).

## What it does

Measured on the flashed board, this build (`' X .` prints the word's xt or names the miss):

```
0 BLOCK .            -> 2438 ok          (address of the 128 B block window)
65 0 BLOCK C!        -> ok
SAVE .               -> 0 ok             (checksummed write, through the main core, into a flash partition)
0 BLOCK C@ .         -> 65 ok            (read back, checksummed the other way)

: FIB DUP 2 < IF ELSE DUP 1- FIB SWAP 2 - FIB + THEN ;
10 FIB .             -> 55 ok
15 FIB .             -> ERR_STACK        (too deep for 16 cells - named, not wrong)

' SEAL .             -> 446 ok           (the store's seal is resident)
' BLOCK .            -> 3962 ok          ' LOAD . -> 3954 ok
' SPAWN .            -> SPAWN?           (tasks are NOT in this image - see "the memory we reclaimed")
```

A **program**, on the other hand, is not typed in: it is a chain of phases built through the store by
`./cli.py` (see "Programs are chains of phases"), which is how a 999 B window runs a 1 328 B cipher and a
radio stack that would never fit the dictionary.

Compiled words, recursion, `DO..LOOP`, `IF/ELSE/THEN`, `CREATE`/`CONSTANT`, case-insensitive lookup,
backspace, `ok`, named errors - a real Forth REPL, on a coprocessor.

## How it works

**Boot.** The main core loads the ULP image into RTC slow RAM, arms a wake timer (6.46 us/tick, about
1 000 ticks per wake), and starts two tasks: a **byte pump** (UART <-> ring buffers) and a **block
server**. Then it does nothing else.

**A wake.** The ULP drains up to 32 command bytes from the ring, echoes them, and on a newline calls
`interpret()`:

1. parse a token into `PAD`
2. **hash it** (DJB2-20)
3. scan the header table - **4-byte entries, `hash20 | xt11 | imm1`**, fixed stride, no names, no links
4. dispatch the 16-bit primitive id through a jump table in `vm_enter`
5. compile (if `:`) or execute

**Memory layout** - three regions that grow toward each other, checked before every write:

```
DICT 56  code area (code field + 2-byte tokens + 4-byte literals)   -> grows up
         ...app space: 1 453 B after the reclaim, 786 B used at boot...
HDRTOP   header table growing DOWN from BLKADR (BLKADR = MEMSZ - 128)
BLKADR   the 128 B block window sits between the headers and the end of mem[]
MEMSZ 2 566 = end of mem[]
```

**Blocks.** `BLOCK` writes 4 words into a mailbox (block, op, checksum), rings a doorbell, and polls for
status. The main core copies **128 B** between its store and the ULP's window, sums both directions, and
writes the status **last** so the ULP can never read a half-copied buffer. The ULP never touches flash or
PSRAM - it cannot.

**Tasks (source only, not resident).** Two VM snapshots of 136 B each (`DS[16]`, `RS[16]`, `SP`, `RSP`, `W`,
`IP`). `SPAWN` takes a word by name, the scheduler steps one task per wake after the drain finishes, `PAUSE`
rotates. The shipping image leaves this out (`' SPAWN .` -> `SPAWN?`) because those bytes buy app space instead -
docs/23 prices both sides of that trade.

**Messages.** The ULP emits **one byte** per message (`0x81`-`0x90`); the host expands it from a table
both cores generate from one X-macro. Zero message strings exist in the ULP image, and the operator's
transcript is byte-identical to when it did.

## Where the bytes went

| | |
| --- | --- |
| ELF sections | text **4 834** + data **2 584** + bss **513** = **7 931 B** (`riscv32-esp-elf-size`) |
| ULP binary on the wire | **7 424 B** (boot banner; `ulp_main.bin`) |
| pool used | **7 845 / 7 856** - the pool is the budget authority (`flash_safe.sh`), 11 B spare |
| `MEMSZ` | **2 566** (the resident dictionary + block window live in `.data`) |
| resident, sealed | **2 438 B** |
| phase window | **999 B** in this budget; **1 193 B** with the dispatcher-only launcher (`./cli.py --library`) |
| block store | flash partition, 128 B blocks, `BLK1` superblock, 32 blocks per sector - no longer the HP core's RAM |
| image wall | an 8 027 B build **does not boot**; every byte of `.text`/`.bss` saved becomes app space 1:1 |

That came from four measured levers: hash headers **-406 B**, `-msave-restore` **-224 B**, one-byte
messages **-104 B of rodata**, `NTSK 3->2` **-152 B** - plus earlier work (`lhu` fetch, number-first
parse, hand-written copies).

## Why it is not a toy

- **The main core is provably a byte pump**: `probe/repl/tools/assert_ulp_only.py` runs six static checks
  on the image plus a counterfactual build whose ULP is a 132 B stub - that one returns `b''` while the
  real one answers `2 3 + .` -> `5 ok`.
- **Every byte is auditable**: each capability has a measured price, and each optimisation was adopted or
  rejected with a number (`-Oz` is byte-identical to `-Os`; `-fno-jump-tables` costs +88 B net).
- **Failures are named**: `ERR_STACK`, `ERR_DIRTY`, `ERR_TASKS`, `ERR_CRC`, `ERR_RANGE`, `ERR_BUFOVER`,
  `ERR_DICT`, and an unknown message code names itself. No silent defaults.
- **A host suite plus board gates**, one of which is documented as decorative because its bug is target-only (see
  `probe/EVIDENCE.md` E-080): a test that cannot fail is not coverage, and the record says which.

## Honest limits

A **typed-in** program has the resident dictionary to grow in (1 453 B of app space, was 690 B), and a **built**
program gets one phase window at a time (999 B here, 1 193 B with the dispatcher-only launcher) - it must be chained to
exceed that. Recursion depth **15** (1 cell per level; 16 is refused with `ERR_STACK`). One block request in flight, and a
timeout wedges the layer until reset. Tasks (`SPAWN`) are implemented but **not resident** in the shipping image - they
are what paid for the reclaim. No names in the dictionary, so no `WORDS` or `SEE`.

## What is left

**R7 - persistence: done.** The store is a raw `esp_partition` with a `BLK1` superblock and 128 B blocks, so a chained
program survives reset and the bound is the partition, not RAM (docs/22). What that unlocked is the phase model above.

**The open item is the radio, and it is one direction.** Our stack receives a stock Meshtastic node and its own frames are
byte-identical to Meshtastic's encoding, but no stock node has ever decoded our transmission. `docs/32-handoff-meshtastic-interop.md`
is the complete state: every experiment, every result, the instrumentation traps, and the ranked hypotheses.

Beyond that: more app space (the asm dispatcher is priced at 400-700 B), and the display leg stays cancelled (J-54).

The single sentence version: **the constraint was the architecture, and the architecture now holds - an interpreted,
block-storage, phase-chaining Forth in eight kilobytes, with 11 bytes to spare, and multi-tasking spent on purpose to
make room for programs bigger than the dictionary.**

---

# esp32-rv32 — a Forth machine on the ESP32-S3 ULP RISC-V core

Exploration repo. Goal: a small, persistent, interactive Forth system running on the
ESP32-S3 ULP RISC-V coprocessor (8 KB of RTC slow memory), with cooperative threads and
an event loop, plus a real harness for talking to it from a workstation.

| Doc | What it is |
| --- | --- |
| [`docs/00-background.md`](docs/00-background.md) | Digest of the earlier loose notes, fact-checked against ESP-IDF v5.4, the local toolchain, and the board on the desk. Includes a corrections table — several numbers in the notes were wrong. |
| [`docs/01-proposal.md`](docs/01-proposal.md) | **The current design**: hard requirements R1–R7, scope, resident budget, paging rules, event loop, tasks, interpreter bootstrapping, plus the definition of done and the unchecked acceptance checklist. |
| [`docs/02-harness.md`](docs/02-harness.md) | The "how do we talk to it" engineering: transport topology, wire protocol, bridge firmware, host tool, debug channels, iteration loops, experiment queue. |
| [`docs/03-prototype-review.md`](docs/03-prototype-review.md) | Review of the `uforth.c` reference prototype, by execution: 53 host tests, measured density, and the four defects that block the ULP port. |
| [`docs/06-repl.md`](docs/06-repl.md) | The command-line REPL (requirement R8): ports, passthrough vs framed modes, the `0x1D` escape table, line discipline, flow control, session lifecycle. |
| [`docs/probes/`](docs/probes/README.md) | **Nine probe briefs** for subagents: what to measure, how, pass/fail, and the exact doc edits each result must hand back. Host probes run in parallel; board probes are exclusive. |
| [`docs/JOURNAL.md`](docs/JOURNAL.md) | **The lab notebook**: every attempt, every measurement, every correction and every dead end, in order. Append-only; kept current as probes report. |
| [`docs/09-display-wiring.md`](docs/09-display-wiring.md) | **Wiring the 1602A to the ESP32-S3**: pin table, power, the three things that go wrong, init sequence, bring-up order. |
| [`docs/08-psion.md`](docs/08-psion.md) | **Next sprint: the Psion-class device.** Hardware spec, the measured budget it must fit, requirements D1–D16, app/overlay model, gates G0–G8, acceptance checklist, risks. |
| [`docs/07-status.md`](docs/07-status.md) | **Status report**: what was asked for, what was measured, what failed, what changed, and what is next — in plain terms. |
| [`probe/EVIDENCE.md`](probe/EVIDENCE.md) | Measured numbers from real builds on this machine (sizes, addresses, section maps) with the exact commands. |
| [`cache/README.md`](cache/README.md) | The one fetch path for external references: write-once, append-only, hashed and journaled. Holds the v5.5 ULP-RISC-V page. |

## Status: it runs

A live Forth REPL on the ESP32-S3's ULP coprocessor. The main core is a byte pump; the interpreter, the
compiler and the prompt are all on the ULP. On the board, measured (E-047):

```
$ probe/repl/repl
ulp forth
 ok
2 3 + .        →  5 ok
: SQ DUP * ;   →   ok
7 SQ .         →  49 ok      ← compiled at runtime, on the chip
BOGUS          →  BOGUS?
```

**Current, measured (shipping build, this branch):** ULP image **7 424 B** (boot banner), pool **7 845 / 7 856**
(`flash_safe.sh` is the budget authority; an 8 027 B image does not boot - docs/30), sealed resident **2 438 B** with a
**1 193 B phase window** for the dispatcher-only launcher (`./cli.py --library` on a fresh board). `HERE` reads **786**
at the prompt. Blocks are in: `' BLOCK .` → `3962`, `' LOAD .` → `3954`, `0 BLOCK .` → `2438`.
Dispatch is **1 139 cycles**/token (was 1 758), a typed literal **1 623** (was ~28 000). There is no display work: that
leg was cancelled (J-54).

**Multi-tasking was live and was then spent.** `SPAWN TA SPAWN TB` printed `1324` (three tasks `131242`) in the era
measured at `MEMSZ` 1 704 with 558 B of app space. The shipping image **trades it for app space**: `' SPAWN .` answers
`SPAWN?` today. The machinery is still in the source behind `P43_TASKS`, and docs/23 prices it: removing it is what paid
for the first big reclaim.

## Programs are chains of phases

This is the design that made everything after it possible, and it is worth stating plainly because it inverts the usual
"one program fits in memory" assumption.

* A **phase** is one *built image*, laid out through the store at a descriptor, and sized to fit the **window above the
  seal** - never larger than the window, so it always fits.
* A **program** is a **chain** of phases. The launcher is handed the first phase's descriptor; every later phase is
  reached by that phase itself executing `CHAIN <descriptor>`. **Descriptor 0 is the end of the chain** (it is also the
  dispatcher's STOP value, so a chain cannot accidentally run past its end).
* **Phases reuse memory; they do not add it.** A chain gives sequence, not space: a phase is swapped in over the
  previous one. Consequence, measured: a phase cannot call another phase's words, so the primitive set must be resident
  and each phase re-declares what it needs (and declares its scratch with `\ SCRATCH: NAME`, one per line, which is what
  the linter checks).
* The resident side stays **thin**: a dispatcher and a registry, nothing else. That is what leaves room for a phase.

Measured: a **24-hop chain** proven end to end, hops at **~2.1 ms**, a **1 193 B window** per phase (dispatcher-only
launcher) versus **254 B** left by the menu launcher *on purpose*, and 15 phases driven from images in the capability
suite. The descriptor map lives in `cli.py`'s `LIBRARY` together with a check that every phase's `CHAIN` literal matches
its successor - without that check a stale chain is silent, because it jumps to a block holding a different image.

This is also why the cipher is split: AES-128-CTR needs **1 328 B** of working state, the window is **999 B**, so the
cipher is **six chained phases**, and the state is handed from one to the next in the radio's own 256-byte buffer (proven
adoptable, docs/31):

| phase | descriptor | size | what it does |
| --- | --- | --- | --- |
| `aesseed` | 80 | 663 B | radio config, nonce, round 0 |
| `aessub` | 88 | 836 B | SubBytes |
| `aessr` | 96 | 722 B | ShiftRows |
| `aesmc` | 104 | 985 B | MixColumns |
| `aesark` | 112 | 898 B | AddRoundKey + round counter, chains back to 76 while round < 11 |
| `aesout` | 72 | 804 B | encrypt, frame, transmit |

## The memory we reclaimed

The wall is real and measured: the ULP image plus its pool is **7 856 B**, and an image of **8 027 B does not boot**.
App space is resident dictionary space, and the image trades against it 1:1 (`.data` holds the pool).

| era | resident app space | how |
| --- | --- | --- |
| book-era build (`MEMSZ` 1 688) | **690 B** | measured at the prompt |
| **after the reclaim** | **1 453 B** | **+763 B, 2.1x** - remove the task machinery from the shipping image and re-bake at `MEMSZ` 2 700 |
| dispatcher-era launcher | window **1 193 B** per phase | thin resident (dispatcher + registry only), fat phases |

Two findings from that work are worth carrying forward. First, the stack high-water is **240 B** on every path exercised
(loads, adopts, executes, 15 phases) against a 324 B painted reserve, i.e. **84 B of slack**, and nothing in the paging
path went deeper - so the reserve is a candidate, not a mystery. Second, the tool that reported it was wrong: the canary
kept the *highest* changed byte instead of the lowest, which reported **1 B** of use for a machine using 240, and sent two
earlier attempts hunting a wrong base. The base was always right.

The reclaim is why the radio fits at all: the LoRa driver and receive path fit in **two phases** (992 B receive, 939 B
transmit), and only the cipher needs the six-phase split above.


**The split is asserted, not assumed.** `probe/repl/tools/assert_ulp_only.py` fails if the main-core executable
contains an evaluator or a copy of the dictionary outside the embedded ULP image, and P41 is the counterfactual:
flash a coprocessor that wakes and does nothing, keep the bridge identical, and the console returns `b''` — no
echo, no prompt, no `ok` — while its wake counter keeps advancing.

Reference material, what each source is authoritative for, and what it cannot answer: `docs/10-references.md`.

**Everything we know, itemised with what it means:** `docs/11-findings.md` — 60 findings across the envelope, time,
the ISA, the machine's structure, the console, the core boundary, the dead ends and the method lessons. Each row
names its pedigree (measured / read / derived); nothing else is admitted.

What those findings would actually *unlock* — including the discovery that multi-tasking's state is already paid for
and only its entry points were garbage-collected: `docs/12-what-opens-up.md`.


* Platform facts: verified against local ESP-IDF `v5.4` sources and the physical board.
* Toolchain: verified by building three stock ULP-RISC-V examples for `esp32s3`
  (`riscv32-esp-elf-gcc 14.2.0`), see `probe/`.
* Board: detected live — ESP32-S3 (QFN56) rev v0.2, 32 MB flash, 16 MB octal PSRAM,
  USB-Serial/JTAG on `/dev/ttyACM0`, CH343 bridge on `/dev/ttyACM1`.
* Nothing written to the board's flash yet. The devkit still holds whatever firmware was
  on it. The `chip-id` / `flash-id` probes are read-only (they do reset the chip).

## Reproduce the probe measurements

```sh
export IDF_PATH=/home/user/research/esp32/esp-idf
. $IDF_PATH/export.sh
cd probe/ulp_gpio            # or ulp_uart_print, ulp_gpio_interrupt
idf.py set-target esp32s3
idf.py build
grep -A20 'Memory Configuration' build/esp-idf/main/ulp_main/ulp_main.map
cat  build/esp-idf/main/ulp_main/ulp_main.ld     # symbols in main-CPU address space
```

Builds are long-running; run them in `tmux` with `nice`, not in the foreground.

---

## The radio: LoRa and Meshtastic, in Forth on the ULP

The same Forth machine also drives an SX1262 LoRa radio, entirely from the coprocessor: an SPI driver, an interrupt
path, a buffer adopt, and an **AES-128-CTR implementation in Forth** split across six store phases (1328 bytes of
working state does not fit the 999-byte phase window, so the state is handed over in the radio's own 256-byte buffer).

Two claims are proven end to end, on hardware:

* Our transmitter's frame is **byte-identical** to what Meshtastic's own Python library builds from the same text
  (`probe/repl/tests/mesh_frame_check.py`, 12/12), and a live frame captured from a stock node was decrypted with our
  nonce + PSK to the exact `Data` protobuf.
* A stock Meshtastic 2.7.26 node's transmissions are **decoded by our stack** (`IRQ 0x0016`, −18 dBm, 2–3 of 4 frames).

The reverse direction is **not** solved and the repo says so plainly: no stock node has ever decoded one of our
transmissions — hundreds of frames across every power, preamble, carrier, PA configuration, LDRO, IQ, sync and frame
content we control, with our firmware on either physical board. Both stock receivers are demonstrably alive
(stock↔stock exchanges text both ways in the same session), and the stock node's own log never shows a packet reaching
its router. Everything measured on our side is correct, so the open question is squarely on the air interface.

Six silent bugs were found and fixed on the way, each now enforced by a lint rule with a mutation test that re-breaks
the code on purpose and requires the rule to name it — see `probe/repl/tools/lint_forth.py` rules **R30–R35** and
`probe/repl/tests/lint_rules_selftest.py`.

| where | what |
| --- | --- |
| [`docs/27-spi-lora.md`](docs/27-spi-lora.md) | the SPI LoRa driver, block by block |
| [`docs/28-sx126x-ulp.md`](docs/28-sx126x-ulp.md) | the SX1262 from the ULP: registers, timing, traps |
| [`docs/29-lora-measurements.md`](docs/29-lora-measurements.md) | every number taken off the air, with the instrument used |
| [`docs/30-forth-lora-driver.md`](docs/30-forth-lora-driver.md) | the Forth driver and its budget |
| [`docs/31-meshtastic-fit.md`](docs/31-meshtastic-fit.md) | **wire facts measured from a real node** — carrier, sync, channel hash, nonce, plus Appendix N (this era) |
| [`docs/32-handoff-meshtastic-interop.md`](docs/32-handoff-meshtastic-interop.md) | **exact state at handoff**: every experiment, every result, the traps, ranked hypotheses |
| [`examples/apps/lora/sync.conf`](examples/apps/lora/sync.conf) | the one source of truth for the sync pair, with its IRQ evidence in comments |

Run the radio gates:

```sh
python3 probe/repl/tools/lintgate.py --repl examples/apps/lora/lorainit.fs examples/apps/lora/lora_rx.fs \
        examples/apps/lora/loratx.fs examples/apps/lora/lora1.fs
python3 probe/repl/tests/lint_rules_selftest.py     # 6 mutants, each must fire
bash probe/repl/tests/run.sh                        # the driver's wire bytes vs the C reference
```

Scope note: all radio work was done against **hardware on this desk**. No API, backend or third-party service was
probed; the protocol facts come from a stock node's own over-the-air emissions and from its published source.

## Where things live

| path | what it holds |
| --- | --- |
| `probe/repl/` | the shipping image: `src/` (engine + ULP harness), `main/`, `tests/` (host suite, board gates, the linter's mutation tests), `bench/`, `tools/` (`bake.sh`, `device_bench.py`, `lintgate.py`) |
| `probe/repl/probe-results/` | per-probe artifacts: `RESULT.md`, the flashed `ulp_main.bin` + `flash_args`, disassembly |
| `probe/results/` | every probe's `RESULT.md` and kept images, P01 … P52 |
| `probe/research/P54-*` | the five lever probes: `FINDINGS.md` (measured), `TASK.md` (the brief), diffs and tools |
| `docs/` | `JOURNAL.md` (J-01…J-102), `11-findings.md` (F-001…F-121), `14-probe-rules.md` (R1–R12), probe briefs |
| `CONSTRAINTS.md` | every constant the design rests on, with a confidence label and how to re-measure it |
| `docs/15-super-optimization.md` | the full idea inventory for application space: ~40 levers, ranked, with falsifiers and a verification protocol |
| `archive/` | superseded trees and old build logs, kept rather than deleted — see `archive/README.md` |
| `cache/` | the write-once fetch cache; it grows and is never pruned |


---

## Publishing

`docs/SHARING.md` records what is published, what is deliberately not (raw flash dumps contain per-device keys;
Meshtastic's GPL firmware is fetched rather than redistributed), and the exact commands to publish this repo.
