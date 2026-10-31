# An interpreted, multi-tasking, block-storage Forth in eight kilobytes, with 3 bytes to spare.

**What it is.** A Forth machine that lives entirely inside the ESP32-S3's 8 KB coprocessor. You type
Forth at a serial console; the ULP interprets and compiles it on-chip, runs it, multi-tasks it, and reads
and writes durable blocks through the main core — which never executes a single token of Forth.

The whole machine — interpreter, dictionary, two task slots, console ring, block client, error paths —
is **7 853 of 7 856 bytes**.

## What it does

```
0 BLOCK .            -> 1072 ok          (address of the 128 B window)
65 0 BLOCK C!        -> ok
UPDATE               -> ok
SAVE .               -> 0 ok             (checksummed write to the main core's store)
0 BLOCK C@ .         -> 65 ok            (read back, checksummed the other way)

: FIB DUP 2 < IF ELSE DUP 1- FIB SWAP 2 - FIB + THEN ;
10 FIB .             -> 55 ok
15 FIB .             -> ERR_STACK        (too deep for 16 cells - named, not wrong)

1 BLOCK .            -> ERR_DIRTY -7     (refuses to clobber unsaved edits)

SPAWN TA SPAWN TB    -> 1324             (two compiled words interleaving)
SPAWN TA SPAWN TB SPAWN TC -> ERR_TASKS  (only two slots, and it says so)
```

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
0        code area (code field + 2-byte tokens + 4-byte literals)       -> 578
         ...154 B of free program space...
904      header area, 85 words x 4 B, growing DOWN                      -> 1244
         BLKADR = 1072: the 128 B block window sits below the headers
1200     end of mem[]  (MEMSZ)
```

**Blocks.** `BLOCK` writes 4 words into a mailbox (block, op, checksum), rings a doorbell, and polls for
status. The main core copies **128 B** between its store and the ULP's window, sums both directions, and
writes the status **last** so the ULP can never read a half-copied buffer. The ULP never touches flash or
PSRAM - it cannot.

**Tasks.** Two VM snapshots of 136 B each (`DS[16]`, `RS[16]`, `SP`, `RSP`, `W`, `IP`). `SPAWN` takes a
word by name, the scheduler steps one task per wake after the drain finishes, `PAUSE` rotates.

**Messages.** The ULP emits **one byte** per message (`0x81`-`0x90`); the host expands it from a table
both cores generate from one X-macro. Zero message strings exist in the ULP image, and the operator's
transcript is byte-identical to when it did.

## Where the bytes went

| | |
| --- | --- |
| pool used | **7 853 / 7 856** |
| ULP image | 6 780 B |
| rodata | 308 B - **only** the dispatch jump table (67 x 4) |
| mem[] | 1 200 B: 578 code + 340 dictionary + 154 free + 128 block window |
| dictionary | **340 B for 85 words** (730 B with names and links) |

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
- **Nine host tests**, one of which is documented as decorative because its bug is target-only (see
  `probe/EVIDENCE.md` E-080): a test that cannot fail is not coverage, and the record says which.

## Honest limits

154 B of program space (a few small definitions). 128 B blocks, 8 of them, **in the main core's RAM - no
flash, no PSRAM** (R7 unwritten). Recursion depth ~13 before `ERR_STACK`. One block request in flight, and
a timeout wedges the layer until reset. No names in the dictionary, so no `WORDS` or `SEE`.

## What is left

**R7 - persistence**: replace the RAM store with a flash partition (4 KB erase vs 128 B blocks is the open
design question), which turns 8 blocks into megabytes without touching the protocol. Then `SD 32` when
bytes allow, and program space beyond 154 B.

The single sentence version: **the constraint was the architecture, and the architecture now holds - an
interpreted, multi-tasking, block-storage Forth in eight kilobytes, with 3 bytes to spare.**

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

**Current, measured:** image **6 888 B** on the wire; pool **7 852 / 7 856** (`.text`+`.rodata` 5 168, `.data` 1 720,
`.bss` 964); `MEMSZ` 1 704 with `V_HERE` 1 146 at boot → **558 B of app space**; C-stack reserve 340 B.
**Multi-tasking (R4) is live**: `SPAWN TA SPAWN TB` with `PAUSE` bodies prints `1324`, three tasks `131242`.
Dispatch is **1 139 cycles**/token (was 1 758), a typed literal **1 623** (was ~28 000). Blocks are **not** in this
image: 456 B of words + a 512 B buffer + ~500 B of plumbing against 558 B of app space (E-062).
rodata **4 818 B**, baked dictionary **1 280 B**. Not yet in the image: blocks (`BLOCK`/`SAVE`) and tasks.
There is no display work: that leg was cancelled (J-54).

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
