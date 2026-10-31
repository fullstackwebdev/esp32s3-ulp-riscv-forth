# P39 — First execution of our engine on the ULP

| | |
| --- | --- |
| Result | **PASS.** The interpreter ran on the coprocessor and printed the right answer: `2 3 + 4 * .` → **`20`**, arriving on UART0 as the two bytes `0x32 0x30` (`P39 OUT len=2 word=0x00003032`), with `wake_count = 60`, `stage = 3`, `errf = 0`, `sp = rsp = 0`, no trap (`RTC_CNTL_INT_RAW = 0x00000000`), and `rdcycle` at wake start = **187**. The engine at P38's width (16-bit tokens, paging removed, no blocks) is **4 314 B** of code+rodata by the minus-control convention, **5 594 B** with the 1 280 B baked prelude, and the flashed ULP `.bin` is **5 876 B** of the 7 856 B pool. One deviation from the brief's method, forced by a measurement: **the prelude is not compiled on the ULP** — compiling it on-chip was measured at **14 874 B against a 7 856 B pool**, so the image carries the host-compiled dictionary (the path `uforth.c`'s own header documents) and `main()` interprets the line against it. That overrun is §1.3 and it is the probe's most useful number after the `20`. |
| Runs on | **board, once.** Flashed over `/dev/ttyACM1` (UART0), captured with pyserial to `logs/run.log`, board lock held in the flashing shell (`run.sh`), every command under `timeout` (build 300, device 30, capture 20), nothing piped through `head`, GPIO19/20 untouched, no `&`, no `/tmp`, and nothing written outside `probe/results/P39-first-chip-run/`. |
| Time box | **overrun.** Reading P38/P22/P06 and the engine, two link failures (one size, one `-Werror=format`), one arithmetic mistake in the first capture, and the measurement of the on-chip-compile overrun cost more than 15 minutes. The *device* work — flash + one gated run — took 2 minutes of wall clock. |
| Depends on | P38 (engine + fixed prelude), P22 (build recipe, `nm -S` discipline, `MEMSZ` ↔ engine coupling), P34/P36 (`pre.fs`'s `.`), P05 (tick, `rdcycle`), P06 (HP staging, wake semantics) |
| Blocks | G2 |
| Sources | `src/uforth.c` = **P38's engine verbatim except one move**: `boot_init()` was lifted out of `#ifdef HOST` into the engine so a ULP image *can* build a dictionary (it is not called by the shipped image — see §1.3). `src/p39_prelude.fs` = **P38's `boot16.fs` verbatim** + `WHILE`/`REPEAT` (boot_min's shape with P38 fix 1's `W,`) + `.` (verbatim from P34/P36's `pre.fs`). `src/ulp_p39.c` = the harness: four hooks, `main()`, the one line. `main/p39_main.c` = the HP half. |
| Artifacts | `artifacts/ulp_main.bin` (5 876 B, the ULP image as flashed), `artifacts/ulp_main.elf`, `artifacts/ulp_main.map`, `artifacts/p39_first_chip_run.bin` (the HP app), `artifacts/flash_args`, `artifacts/host_p39` (host build of the same engine+prelude), `artifacts/ulp_p39.o` / `artifacts/ulp_p39_ctl.o` (the size pair), `src/image.h` (the baked dictionary) |
| Logs | `logs/build.log`, `logs/flash_and_capture.log`, `logs/run.log` (the serial capture — 1 381 bytes) |

## Record

| Item | Value |
| --- | --- |
| engine `.bin`, and minus the control stub | **5 876 B** flashed `.bin` (`.text` 4 306 + `.rodata` 277 + `.data` 1 288 + 5 pad); control (hooks + `main`, no engine) **282 B** of sections ⇒ **5 594 B**, of which **1 280 B is the baked prelude dictionary** ⇒ **4 314 B of engine code+rodata** |
| `nm -S` allocation check | **frames/segments absent by design, `mem`/`vm_live`/`tsk` present**: `mem` `0x00000500` (1 280, `.data`), `tsk` `0x000001a4` (420), `vm_live` `0x00000088` (136), `tib` `0x80` (128), `ds`/`rs` 64 each; `nm -S \| grep -c "frm\|ptab\|blk"` = **0** |
| output bytes on the wire | `P39 OUT len=2 word=0x00003032 byte0=32 byte1=30` → **`0x32 0x30`** = `"20"` |
| interpreted result | **`20`** — the expected value, and `P39 PASS answer=20` printed by the HP itself |
| `wake_count` | **60** in a 400 ms window at period 1 000 ticks (6 460 µs) — 400/6.46 = 61.9 expected |
| `rdcycle` at wake start | **187** |
| failure mode, if any | **none.** No trap (`RTC_CNTL_INT_RAW=0x00000000`), never-ran disproved (`wake_count` 0 before the run, 60 after, same at a second read), wrong-answer disproved (`len=2`, bytes `"20"`, `errf=0`, `stage=3`) |
| what is flashed now | the P39 app at `0x10000` (P39 ULP image embedded), bootloader `0x0`, partition table `0x8000`; ULP timer **disarmed** at exit (`RTC_CNTL_ULP_CP_TIMER = 0x00000000`, `slp_timer_en=0`), ULP not armed |
| period actually used | `ulp_set_wakeup_period(0, 6460)` — the API takes **microseconds** and converts with the calibrated RTC slow clock; 6.46 µs/tick from P05, so 6 460 µs *is* the probe's "1 000 ticks" |

## 1. Answers

### 1.1 Does it run, and is the answer right?

**Yes, on the first armed run.** The complete serial record of the experiment (from `logs/run.log`,
1 381 bytes total including the ROM banner):

```
P39 BOOT stage=wdt wdt_init=0
P39 BOOT stage=image bin=5876 bytes (stub floor 142 B, so engine+prelude+harness)
P39 READY stage=console — send 'g' on UART0 (115200) to arm the ULP

[capture] sent 'g' at t+0.20s
P39 GO gate=console
P39 LOAD rc=0 period_ticks=1000 period_us=6460
P39 BEFORE wake_count=0 stage=0 done=0
P39 RESULT wake_count=60 stage=3 done=1 here_boot=1136 here_prelude=1136
P39 OUT len=2 word=0x00003032 byte0=32 byte1=30 byte2=00 byte3=00
P39 OUT as-string="20  "
P39 STACK sp=0 rsp=0 errf=0
P39 CYC rdcycle_at_wake_start=187
P39 REG trap_int_raw=0x00000000 cocpu_ctrl=0x0B4FC811 slp_wakeup_cause=0x00000000 wake_count_second_read=60
P39 PASS answer=20
P39 STATE ulp_cp_timer=0x00000000 slp_timer_en=0 (0 = disarmed)
P39 done
```

`stage=3` is the last stage marker: `1` = dictionary present, `2` unused in this image, `3` = the line
was interpreted with `errf = 0`. The two output bytes are the *engine's own* `EMIT` calls out of `.`: the
digit `2` (`0x32`) then `0` (`0x30`). `sp = rsp = 0` means the line left nothing behind and the stack
did not wrap — the failure mode P38 found hiding under a "passing" test.

`rdcycle = 187` at wake start is the wake-entry cost as seen from `main()`'s first instruction. It is
higher than P05's **81** because P05 measured entry into an *assembly* kernel: here the C prologue of
`main()` — saving the registers the engine needs — is inside the stamp. That is the honest number for
this image, and it is 163 cycles (8.6 µs) below one RTC tick, so nothing about the period is at risk.

### 1.2 The three failure modes, and which ones were ruled out — by construction, not by hope

* **trap** — `RTC_CNTL_INT_RAW` (bit 17 = `RTC_CNTL_COCPU_TRAP_INT_RAW`) is `0x00000000`; `wake_count`
  is 60 at both reads, i.e. the core kept retiring wakes to the end of the window.
* **never runs** — `P39 BEFORE wake_count=0 stage=0 done=0` is printed *before* arming, and
  `wake_count=60` after: the counter's advance is the proof the loader and the timer bit were right.
* **runs but wrong** — the raw bytes are published as a word (`0x00003032`) *and* as four hex bytes
  *and* as a string, and the final `sp`/`rsp`/`errf` are published with them, so a wrong answer would
  have arrived with the stack it died on. `len=2` also proves `.` printed exactly two bytes: a silent
  `EMIT` drop or a stray `ok` from an accidental REPL would have changed the length.

The first capture attempt saw **zero bytes** and that is a fourth, self-inflicted mode worth recording:
esptool ends with `Hard resetting via RTS pin`, and the flasher closes the port as the app starts, so a
plain re-open waits 20 s for a banner that has already gone by. `capture_reset.py` asserts RTS (EN) for
150 ms with DTR (IO0) released, and the whole run then lands inside the window. **A capture that does
not reset the chip looks exactly like "the ULP never ran"** — that is now a GUARDRAIL in the script.

### 1.3 The one deviation, and it is a measurement: the prelude is not compiled on the ULP

The brief's method step 2 asks the image to compile its prelude on-chip, and §Question asks whether the
interpreter "compile its prelude" on the coprocessor. The first build attempted exactly that — `boot_init()`
plus `interpret()` over `src/p39_prelude.fs`'s 3 685 B of text — and **the link failed by 7 018 B**:

```
ld: address 0x2f0e of ulp_main.elf section `.rodata' is not within region `ram'
ld: address 0x2f18 of ulp_main.elf section `.data'   is not within region `ram'
ld: address 0x3a1c of ulp_main.elf section `.bss'    is not within region `ram'
sections: .text 0x1e10 (7696)  .rodata 0x10fe (4350)  .data 8  .bss 0xb04 (2820)   total 14 874
```

Two of those bytes are worth more than the run itself:

| line | B | why |
| --- | --- | --- |
| engine `.text` | 4 306 | the real engine (this is what the image carries) |
| **a second dispatch instantiation** | **+4 336** | `interpret()` is `static`; GCC inlined `run()`/`vm_enter()` and the whole 62-body switch into `main()` **as well as** keeping the 2 918 B copy in `interpret()`. Object-level sizes: `.text.startup.main` 4 336 **and** `.text.interpret` 2 918 |
| prelude source text | +3 685 | `.\`-comments included; the code itself is ~1.1 kB |
| `.rodata` overhead | +665 | the 264 B jump table + the error strings |
| `.bss` | +2 820 | `mem` 2 048 + rings/mailbox/stacks |

So the ULP image therefore takes the path `uforth.c`'s own header comment describes — "compiled on a PC
into `image.h` and baked into the ULP binary" — and `main()` interprets the line against that dictionary.
`build.sh` regenerates the dictionary from the same engine source on every build and **fails the build**
if the host does not print `20` first, so the baked prelude is not a stale blob:

```
--- host: prelude + the one line (must print 20, then nothing) ---
image: 1136 bytes of 1280 (144 free)
20
```

What this does *not* answer: whether the outer interpreter can compile 24 colon definitions on the chip
*in a pool that also holds them*. The 4 336 B duplicated instantiation is the first thing to fix (a
`noinline` on `interpret`, or one call path), and `P22`'s "engine grows when `MEMSZ` shrinks" coupling
applies on top of it. That is follow-up 1, and it has a number now instead of a guess.

### 1.4 Size, by the minus-control discipline

```
$ riscv32-esp-elf-size -A build/esp-idf/main/ulp_main/ulp_main.elf
.text    4306   .rodata  277   .data  1288   .bss   772      (region 7856 -> 6 643 used, 1 213 left)
.bin     5876
$ nm -S --size-sort ulp_main.elf | grep " [bBdD] "
000011ec 00000500 d mem            1280 B, .data (the baked dictionary; .data *is* in the .bin)
000016f4 000001a4 b tsk             420
00001918 00000088 b vm_live         136
00001898 00000080 b tib             128
000016ec 00000004 d p39_magic         4     (nonzero on purpose: a 0 would land in .bss)
000019c8 00000004 B p39_wake_count    4
000019c4 00000004 B p39_cyc_start     4
000019c0 00000004 B p39_stage         4
000019b4 00000004 B p39_out_word      4
000019b0 00000004 B p39_out_len       4
000019ac 00000004 B p39_sp            4
000019a8 00000004 B p39_rsp           4
```

Frames, the page table, the LRU reserve and every block symbol are **absent** (`nm -S | grep -c
"frm\|ptab\|blk"` = **0**), exactly as the probe's allocation check requires: `-DP33_NOPAGE` removed
2 048 B of frames + 16 B of table, and `-DP33_BLOCK` was never defined, so P38's 530 B block layer is
not in this image either.

| | B | note |
| --- | --- | --- |
| flashed ULP `.bin` | **5 876** | `.text` 4 306 + `.rodata` 277 + `.data` 1 288 + 5 pad |
| control (hooks + `main`, no engine) | **282** | the same TU with `-DP39_HARNESS_ONLY`, which drops `uforth.c` and `one_line()` |
| engine, minus control | **5 594** | includes the dictionary |
| minus the baked prelude dictionary | **4 314** | = **the engine at 16-bit tokens, no paging, no blocks** |
| pool left | **1 213** (6 643 of 7 856) | stock `ulp_riscv.ld`, `LENGTH = 8176`; `.bss` ends at 6 648 and the C stack needs 320 of the remaining 3 528, so P21's line is **not** binding here |

**4 314 B is the number the next probe measures against**, and the control is an object-level pair
(282 B of sections) rather than a second link — stated plainly because P22's convention was
`.bin − control .bin`. The `.bin` figure itself (5 876) is the flashed artifact.

### 1.5 The prelude the line needed, and why `.` is a decision

P38's `boot16.fs` — the prelude the probe says to use — **has no `.`**. Its primitive set is P32 D's
(`EXIT LIT BRANCH 0BRANCH (DO) (LOOP) (+LOOP) I J UNLOOP EXECUTE DUP DROP SWAP OVER ROT >R R> @ ! C@ C! W@ W!
+ - * /MOD U/MOD AND OR XOR INVERT LSHIFT RSHIFT 0= < U< KEY KEY? EMIT TYPE , W, C, : ; CREATE CONSTANT '
['] LITERAL ." (.") \ ( GPIO@ GPIO! ADC@ MS WAKE PAUSE FAULT`), so `2 3 + 4 * .` cannot load against it
at all: it dies on `. ?` — the same class of load-time stop that cost P37 a whole run.

The additions are therefore three words and they are **verbatim from earlier probes, not invented**:

* `WHILE`/`REPEAT` — `boot_min.fs`'s shapes with P38 fix 1's width (`['] 0BRANCH W, 0 W,` and
  `['] BRANCH W, W,`), because `,` is `a4()+wr32` and would write `[token][00 00][operand]`;
* `.` — copied from `P34-forth-paging/src/pre.fs` / `P36/src/pre.fs`, the version already used to print
  decimal on this engine, including its `BEGIN DUP WHILE … REPEAT` shape.

They are in `src/p39_prelude.fs`, they are **not** in P38's file (P38's tree is untouched), and the host
build is the evidence they are right: `image: 1136 bytes of 1280` then `20`. If the orchestrator prefers
the strict reading ("boot16.fs, unmodified"), then the line has to change instead — but `20` cannot be
printed without a printing word, so one of the two has to move, and this is the smaller move.

### 1.6 What the HP side does, and the one board rule that shaped it

```
wdt first (12 s, reconfigure when IDF already initialised it)  -> P39 BOOT stage=wdt wdt_init=0
image size printed before anything is armed                    -> P39 BOOT stage=image bin=5876
banner + 'g' gate on UART0                                     -> P39 READY / P39 GO gate=console
timer stopped, 20 ms, load_binary                               -> P39 LOAD rc=0
period set, run                                                -> 400 ms window, WDT fed each ms
timer stopped, 50 ms for the in-flight wake to retire          -> P39 RESULT …
registers read, verdict printed, timer disarmed                 -> P39 PASS / P39 STATE slp_timer_en=0
```

The HP **never writes** a `COCPU_*` register and **never writes the ULP's variables**: every `p39_*`
value is written by the ULP and read by the HP through a `volatile` accessor (P06's GUARDRAIL — a direct
read lets the optimiser cache the first snapshot). All ULP-side state is initialised *on the ULP* at its
first wake, keyed by a nonzero `.data` magic, because **`.bss` is not in the ULP `.bin`** and RTC RAM
survives from whatever the previous image left there.

## 2. Evidence

```sh
cd probe/results/P39-first-chip-run
timeout 300 ./build.sh                       # host: prelude+line -> "20"; then idf.py build  (logs/build.log)
timeout 200 ./run.sh                         # board lock, chip-id, flash, capture          (logs/flash_and_capture.log)
timeout  20 python3 capture_reset.py /dev/ttyACM1 logs/run.log    # the gated run             (logs/run.log)
timeout 120 bash artifacts/size2.sh          # real vs control object: 7033 vs 282 B
cd build/esp-idf/main/ulp_main && riscv32-esp-elf-nm -S --size-sort ulp_main.elf
riscv32-esp-elf-size -A build/esp-idf/main/ulp_main/ulp_main.elf
```

### 2.1 Build and host pre-check

```
prelude: 59 lines, 3685 bytes of text
--- host: prelude + the one line (must print 20, then nothing) ---
image: 1136 bytes of 1280 (144 free)
20
Project build complete. To flash, run:
```

### 2.2 Flash

```
esptool v5.3.1 — Connected to ESP32-S3 on /dev/ttyACM1 (revision v0.2), MAC xx:xx:xx:xx:xx:xx
Wrote 227488 bytes (122875 compressed) at 0x00010000 ... Hash of data verified.
Wrote   3072 bytes (103 compressed)  at 0x00008000 ... Hash of data verified.
Leaving... Hard resetting via RTS pin
FLASH_EXIT=0
```

`artifacts/flash_args` (kept, as required):

```
--flash_mode dio --flash_freq 80m --flash_size 2MB
0x0 bootloader/bootloader.bin
0x10000 p39_first_chip_run.bin
0x8000 partition_table/partition-table.bin
```

### 2.3 Serial bytes around the result (verbatim, `logs/run.log`)

```
P39 RESULT wake_count=60 stage=3 done=1 here_boot=1136 here_prelude=1136
P39 OUT len=2 word=0x00003032 byte0=32 byte1=30 byte2=00 byte3=00
P39 OUT as-string="20  "
P39 STACK sp=0 rsp=0 errf=0
P39 CYC rdcycle_at_wake_start=187
P39 REG trap_int_raw=0x00000000 cocpu_ctrl=0x0B4FC811 slp_wakeup_cause=0x00000000 wake_count_second_read=60
P39 PASS answer=20
```

`here_boot = here_prelude = 1136` is the second independent confirmation of the image's state: `V_HERE`
equals the host dump's own `image: 1136 bytes` and **`boot_init()` never ran** (it would have reset
`V_HERE` to `DICT` = 56). If both had run, the primitive headers would sit on top of the baked prelude
and `.` would have stopped at `.?`.

### 2.4 The flashed image reproduces from the tree

```
artifacts/image.sha256
9021972aa1243f92b535728f3df460305298cfbb1280fc3f910986fe1c351715  artifacts/ulp_main.bin
b515c66b4b83c16f1daaad3d32f8984acde0834b083d528fb87545afece9255e  artifacts/p39_first_chip_run.bin
```

`./build.sh` run again after the last source edit produces **byte-identical** images (both hashes), so
the artifact kept here is the artifact that ran, and the run is reproducible from the probe tree alone.

## 3. Verdict

**PASS on the probe's own criterion — a specific value on a terminal — with one method change that the
build forced and that is priced.**

* the image loads and runs: `wake_count` 0 → **60** in 400 ms at a 1 000-tick period (61.9 predicted);
* the printed result is **`20`**: `len=2`, bytes `0x32` `0x30`, produced by the engine's `EMIT` path out
  of `.`, with `errf=0` and an empty data stack afterwards;
* allocation confirmed by symbol: `mem` 1 280 (`.data`), `tsk` 420, `vm_live` 136, `tib` 128 present;
  **frames, page table and every block symbol absent** (`grep -c` = 0);
* the engine size at 16-bit-without-paging is recorded: **4 314 B** (5 594 B with the prelude,
  5 876 B as flashed), and the pool has **1 213 B** left.

**What changes downstream.** The question this probe exists to answer — *has any of this ever run?* — is
answered **yes**, and the whole approach stops being a design document at this line of the log. But the
run also put a price on two things the plan assumes for free: **compiling the prelude on the chip is
7 018 B over the pool**, half of which is a *compiler accident* (a second copy of the dispatch switch)
and half of which is the prelude **text**, and the engine — 4 314 B with 1 213 B of pool left — has no
room for the block layer's 530 B plus a task layer plus a REPL in the same image. Every later probe that
wants "the interpreter on the chip" inherits this budget, not P22's.

**Failure-criteria check** (none fired, recorded because the probe names them):

1. *Trap* — did not happen; if it had, `RTC_CNTL_INT_RAW & RTC_CNTL_COCPU_TRAP_INT_RAW` plus
   `cocpu_ctrl` and the last `stage` would be the published evidence, and the HP already prints them.
2. *Never runs* — handled by printing `wake_count` **before** arming as well as after; the pre-arm
   `0` and the post-window `60` are both in the log.
3. *Runs, wrong answer* — the raw word, its four bytes, the string form, `sp`, `rsp`, `errf` and both
   `V_HERE`s are on the wire, which is what makes this log diagnosable rather than a claim.
4. *Does not fit* — fired once, on the on-chip prelude compile: 14 874 B against 7 856, §1.3.

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` — G2 status, and R1's first measured on-chip figure

```
**G2 — the interpreter has run on the coprocessor (P39, PASS).** On the ESP32-S3's ULP-RISC-V, at a
1 000-tick period (6 460 us), the image was loaded with `ulp_riscv_load_binary`, armed with
`ulp_riscv_run`, and `2 3 + 4 * .` returned **`20`** — two bytes, `0x32 0x30`, on UART0 — with
`wake_count` 0 -> 60 in 400 ms, `errf` 0, an empty data stack, no trap (`RTC_CNTL_INT_RAW` 0) and
`rdcycle` at wake start **187**. Every number this project has quoted before P39 came from a host
build, a static accounting or an isolated probe image; this one came from the chip.

Budgets it fixes, for everything downstream:

* the engine at **16-bit tokens with paging removed and no block layer** is **4 314 B** of
  code+rodata (5 594 B with the 1 136 B prelude dictionary baked in; the flashed ULP `.bin` is
  **5 876 B**), in a 7 856 B pool with **1 213 B** left and no frame/page-table/block symbols in
  `nm -S`. P38's 530 B block layer and P22's 2 048 B of frames are not in that number.
* **compiling the prelude on the chip does not fit**: 14 874 B measured against 7 856 — 4 336 B of
  it a *second* instantiation of the 62-body dispatch switch (`interpret()` is `static`, so GCC
  inlined `run()`/`vm_enter()` into `main()` while keeping the copy in `interpret()`), 3 685 B the
  prelude source text, 2 820 B `.bss`. The shipped image therefore carries the host-compiled
  dictionary, which is what `uforth.c` always documented. The plan must budget the prelude **text**
  (or a `noinline` fix) before it budgets on-chip compilation.
* `rdcycle` at wake entry is **187** in a C `main()` — not P05's 81, which was measured entering an
  assembly kernel. Use 187 for a C entry point; it is 8.6 us against a 6.46 ms period, i.e. 0.13 %.
```

### 4.2 `docs/JOURNAL.md` — the first on-chip execution, with the bytes

```
**It runs.** The first time any of this executed on the coprocessor: the ULP-RISC-V on an ESP32-S3 was
loaded with our 16-bit-token engine, armed at a 1 000-tick period (6 460 us) and asked for one line,
`2 3 + 4 * .`. The answer came back over UART0 as two bytes — `0x32 0x30`, "20" — after 60 wakes, with
`errf` 0, an empty data stack, no trap, and `rdcycle` at wake start 187. 5 876 B of image in a 7 856 B
pool.

The one requirement that was not free: P38's prelude has no `.`, so the line could not load against it
(`` . ? ``). Three words were added — `WHILE`, `REPEAT` and `.` — all copied from earlier probes
(`boot_min.fs`'s shapes with P38's `W,` width; `P34`/`P36`'s `pre.fs` for `.`), none invented. And the
bigger finding: compiling that prelude *on the chip* is **7 018 B over the pool** — half of it a
compiler accident, because `interpret()` is `static` and GCC inlined the whole 62-primitive dispatch
switch into `main()` as well as keeping its own copy (4 336 B extra), and half of it the 3 685 B of
prelude text. So the image carries the host-compiled dictionary, the way `uforth.c`'s header always
said it would, and the build refuses to produce an image unless the host has just printed `20` from the
same source. Two more small ones for the next run: `.bss` is not in a ULP `.bin`, so every "have I run
before?" flag has to be a nonzero `.data` magic; and a capture that does not *reset* the chip sees zero
bytes, which looks exactly like "the ULP never ran" — assert RTS (EN), leave DTR (IO0) released.
```

### 4.3 `probe/EVIDENCE.md` — the engine's real `.bin` size on the chip build

```
### E-033 — the engine runs on the ULP and answers 20 (P39)

`probe/results/P39-first-chip-run/`, ESP32-S3, flashed over /dev/ttyACM1, one gated run.

* `2 3 + 4 * .` -> **20** as `0x32 0x30` on UART0; `wake_count` 0 -> **60** in 400 ms at period
  1 000 ticks (6 460 us); `rdcycle` at wake start **187**; no trap; `sp = rsp = 0`, `errf = 0`.
* Engine at 16-bit tokens, `-DP33_NOPAGE`, no `-DP33_BLOCK`: **4 314 B** of code+rodata
  (**5 594 B** with the 1 136 B baked prelude dictionary; flashed `.bin` **5 876 B**), control
  (hooks + `main`, `-DP39_HARNESS_ONLY`) **282 B**. Pool: 6 643 of 7 856 B used, 1 213 left.
  `nm -S`: `mem` 1 280 `.data`, `tsk` 420, `vm_live` 136, `tib` 128; **no** `frm`/`ptab`/`blk*`.
* **Compiling the prelude on the chip does not fit**: 14 874 B (`.text` 7 696, `.rodata` 4 350,
  `.bss` 2 820) vs 7 856. 4 336 B of that `.text` is a second instantiation of the dispatch switch
  (`interpret()` is `static`; `run()`/`vm_enter()` inlined into `main()` *and* kept in `interpret()`),
  3 685 B is the prelude text. The image therefore bakes the host-compiled dictionary, and `build.sh`
  fails unless the host prints `20` first.
* Method notes: `.bss` is not part of a ULP `.bin` (first-entry state must be a nonzero `.data`
  magic); `ulp_set_wakeup_period()` takes **microseconds** — 1 000 RTC ticks is 6 460 us at P05's
  6.46 us/tick; and a capture must assert RTS (EN) to reset the chip, or the banner is missed and a
  silent log looks like "never ran".
```

## 5. Follow-ups

1. **The duplicate dispatch instantiation is 4 336 B of free money.** `interpret()` is `static`, so GCC
   inlined `run()`/`vm_enter()` (and all 62 primitive bodies) into `main()` while keeping a 2 918 B
   copy in `interpret()`. One `__attribute__((noinline))`, or a single call path, would put the switch
   in the image **once** and bring on-chip prelude compilation from 14 874 B to ~10 500 B — still over
   7 856, but within reach of stripping the prelude's comments (~2.5 kB) and dropping the outer
   interpreter from the image entirely when the program is precompiled. That is the probe that decides
   whether the chip can compile Forth or only run it.
2. **`MEMSZ` 1 280 has 144 B of dictionary headroom.** P22's coupling (`P()`'s `a < MEMSZ` bound is
   inlined ~20 times) means the engine line moves with the pool, so the 4 314 B is the engine **at this
   `MEMSZ`** — moving the pool to fit blocks re-measures the engine.
3. **The `.` word belongs in the prelude for real.** It is currently P39's local addition
   (`src/p39_prelude.fs`), copied from `P34`/`P36`. If the project keeps using it, `boot16.fs` should
   gain `WHILE`/`REPEAT`/`.` — and P34's `pre.fs` should be checked for any other word the port needs
   before the next on-chip probe discovers it at load time again.
4. **`p39_out_word` holds 4 bytes.** Enough for one decimal answer, deliberately; a real `TYPE` of a
   string needs the out-buffer as an array, and the IDF map generator only exports scalars cleanly (a
   `u32` array needs a word-indexed scheme on the HP side, or a mailbox).
5. **The on-chip path still never ran `boot_init()`.** It compiles and it is now in the engine (not in
   `#ifdef HOST`), but nothing has executed it on the ULP. If follow-up 1 lands, that is the first
   thing the next image must prove — with `here_boot` published *before* the first `find()`.
6. **Keep `artifacts/flash_args` and `artifacts/ulp_main.bin` with the result** — done — because "what
   is on the board" has to be answerable from the probe tree alone.
