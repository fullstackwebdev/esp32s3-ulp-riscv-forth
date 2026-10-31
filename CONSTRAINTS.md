# CONSTRAINTS.md — the machine's constants

Every number the project relies on, with how it was obtained. This file exists because a stale constant is
worse than no constant: "620 B of app space" survived for weeks and cost a probe to disprove (F-06).

**Every entry carries a confidence label. Never quote an `E` as if it were an `M`.**

| label | meaning |
| --- | --- |
| **M** | measured on this machine, from a build artifact, the ELF, or the board |
| **D** | derived arithmetic from `M` values — exact, but one step removed |
| **E** | estimated / recalled — **this is a to-do**, and must be re-measured before it is quoted |

Rules this file obeys, learned the hard way:

- A number that came out of a **failing** run is not a measurement. It is unattributable, and once it is in a
  table it is indistinguishable from a real answer.
- Sizes come from compiler artifacts (`riscv32-esp-elf-size -A`, `nm -S`, `.map`), **never** from parsing a
  `#define` and doing the arithmetic by hand.
- Pool overflow is **silent**: the link succeeds and the ULP's C stack runs into `.bss`. Measure, do not infer.

---

## 1. Platform and clock

| constant | value | |
| --- | --- | --- |
| RTC slow RAM, total | **8 176 B** | M |
| usable pool | **7 856 B** (the platform reserves 320) | M |
| ULP clock | **≈19.0 MHz ±1.5 %** | M |
| RTC slow clock | **154.9 kHz** (the TRM says 136 — the board disagrees) | M |
| tick | **6.46 µs**, 122.6 cycles | M / D |
| wake entry cost | **81 cycles** | M |
| idle wake rate | ≈30/s (75 wakes in 2.5 s) | D |
| RTC RAM base | `SOC_RTC_DATA_LOW` = 0x5000_0000; the ULP image links at **0**, so published addresses are **offsets** | M |

## 2. Memory image (shipping build)

| constant | value | |
| --- | --- | --- |
| **configuration at HEAD** | main now carries the **overlay build**: `MEMSZ` 1 936, per-phase capacity **690 B**, resident toll 846 B (manager 528 + loop 318), store 128 × 128 B (volatile, host `.bss`) | M |
| **device ceiling (measured)** | **15 phases × 516 B = 7 740 B = 504 %** of the control, stopped by the 128-block store — not by RAM or the window | M |
| **no-overlay control** | `MEMSZ` 2 288, **1 536 B** of application space; still buildable (`tests/abtest.sh`) and preserved at tag `pre-overlay-merge` | M |
| **pool used** | **7 853 / 7 856** (3 B free) — unchanged by P53, which moved 200 B from `.bss` to `.data`; the overlay branch sits at **7 845 / 7 856** after the loader fix (word() refill loop), which is 11 B better than the code it replaced | M |
| `.text` | **4 926 B** (was 5 252) | M |
| `.rodata` | **340 B** — the dispatch jump table plus the P54 binary-op table (+6 B of `.srodata`) | M |
| `.data` | **1 704 B** = `MEMSZ` 1 688 + 16 B of interpreter variables | M |
| `.bss` | **877 B** (task records 280, `vm_live` 136, rings 128+64, `tib` 128, mailbox 16, counters) | M |
| ULP image on the wire | **6 780 B** | M |
| `MEMSZ` | **1 688** | M |
| `BLKADR` | **1 560** = `MEMSZ` − `BLKSZ` 128 | M |
| code area (used) | **578 B** | M |
| dictionary | **255 B for 85 words** (3 B per header: `hash13 \| xt10/2 \| imm1`) | M |
| **free program space** | **727 B** | M |

Shape of `mem[]` at `MEMSZ` 1 688: code **578 B** growing up from `DICT` 56, headers **255 B** (85 words ×
3 B) growing down from `HDRTOP` = `BLKADR` 1 560, block window `[1 560, 1 688)`, and **727 B free** between
code top and the newest header. The two regions are checked before every header write (`ERR_DICT`) — but
**not** before a `,`, see §10 — because once they meet the damage reads as a wrong-word bug, not an error.

**727 B is 4.7× what this machine shipped with, bought without removing a single feature.** Two waves:
P53 found 200 B of `.bss` allocated to a 4-word protocol (`mailbox[54]`); P54 measured three text levers —
a table-driven kernel for 10 same-shape primitives (**−224 B**, dictionary byte-identical), a shared tail for
the error paths (**−52 B**), and 3-byte headers (**−85 B** of dictionary for **−8 B** of text). Every byte
freed in `.text`/`.bss` moves 1:1 into `MEMSZ`, which is 1:1 into application space. The bake and the build
must agree on `MEMSZ` and on every flag that shapes the dictionary — `tools/bake.sh` owns both.

## 3. Per-unit costs

| unit | cost | |
| --- | --- | --- |
| token | **2 B** (16-bit token, 32-bit cell) | M |
| literal | **6 B** (`LIT` token + 4 B cell) | M |
| header | **3 B** = `hash13 \| xt10 (÷2) \| imm1` | M |
| primitive body | **29.5 B** average; 64 bodies = 1 890 B | M |
| dispatcher `vm_enter` | **2 404 B ≈ 50 % of `.text`** | M |
| `VM` struct | **136 B** (`DS[16]` + `RS[16]` + `SP`/`RSP`/`W`/`IP`) | M |
| task slot | ≈140 B; `NTSK` 2 → 280 B | M |
| C stack reserve | 260 B (P21 measured a 244 B floor) | M |
| rings | command 64 B · output 128 B · `TIBSZ` 128 | M |
| **recursion depth** | **15 legal, 16 → `ERR_STACK`** | M |
| **task slots** | **2**; a third → `ERR_TASKS` | M |

## 4. Speed and throughput

| constant | value | |
| --- | --- | --- |
| **dispatch, primitive in a tight loop** | **400.1 and 409.6 cycles** (two independent workloads, within 2.4 %) | M |
| dispatch, literal-heavy line | 1 139 cycles ≈ 60 µs (was 1 758 before the `lhu` fetch) | M |
| cost of compiling one definition | ~17 000–25 000 cycles | M |
| **typed literal** | **1 623 cycles** (was ~28 000 before number-first parse + direct `find`) | M |
| **throughput** | **≈47 500 dispatches/s** at 400 cycles; 16 681 at 1 139 | M / D |
| `arith` on the chip | **6 059 696 cycles / 15 145 dispatches = 319 ms** | M |
| `recursion` on the chip | **2 125 198 cycles / 5 188 dispatches = 112 ms** | M |
| block fetch | **144 µs** polling, **176 µs** doorbell, **3.55 MB/s** | M |
| block fetch in token-equivalents | **≈2.4 tokens' worth of time** | D |
| host poll interval | 1 FreeRTOS tick = **10 ms** → the block latency bound | M |
| `BLKWAIT` | 2 000 000 iterations, ≈0.2–0.4 s | **E** |

The last row matters more than it looks: `BLKWAIT` must exceed the host's poll interval or the **first**
request times out, and a timed-out request deliberately keeps `blk_out` set — so every later call answers
`ERR_BUSY` until reset.

## 5. Storage semantics (measured exactly)

| case | result | |
| --- | --- | --- |
| `HERE CONSTANT VB 0 ,` | `VB` = **590**, `VB @` = **38 666 242** (header bytes), `HERE` after = 600 | M |
| `CREATE V2 0 ,` | `V2` = **604**, `V2 @` = **0** (a real cell) | M |
| interpreter variable offsets | `V_STATE` 0 · `V_HERE` 4 · `V_LATEST` 8 · `V_BASE` 12 · `DICT` 56 | M |

`HERE CONSTANT X` names a header, **not** a variable: `HERE` is read before the header exists, so the
constant's value is the address of its own header. `@` there reads a link field and `!` corrupts the
dictionary. `CREATE X ,` names the body. This mistake was filed as an engine defect (F-119) and
**retracted** after narrowing; `tests/semantics.fs` pins all four rules so it is never rediscovered.

## 6. Benchmark baseline (the acceptance constants)

`./bench/run.sh` compares against `bench/baseline.txt`; `--freeze` rewrites it deliberately.

| workload | result | dispatches above prelude | |
| --- | --- | --- | --- |
| prelude load | — | **261** | M |
| `arith` | **832501** | 15 163 (15.2 per iteration) | M |
| `matrix` | **67000** | 25 651 (51.3 per multiply) | M |
| `recursion` | **144** | 5 230 (11.2 per call) | M |
| `memory` | **120** | 862 (27 per cell store+load) | M |
| `depth` | `0` then `ERR_STACK` | — (aborts before the counter prints) | M |

Units are exact and portable: a checksum, a dispatch count, and an integer limit. **Wall-clock is never
compared** — the host is a different machine, and cycles belong to the board.

## 7. Levers already banked

| lever | delta | |
| --- | --- | --- |
| hash dictionary (names → `hash20\|xt11\|imm1`) | dictionary 730 → 324 B (**−406**) | M |
| `-msave-restore` | `.text` **−224 B** | M |
| one-byte messages (text lives on the host) | `.rodata` 372 → 268 (**−104**) | M |
| `NTSK 3→2` | `.bss` **−140 B**, `.text` −12 B | M |
| `P30_HANDCOPY` | **−356 B** | M |
| `lhu` halfword fetch | **−35.2 %** dispatch cycles, +6 B | M |
| number-first parse + direct `find` | **17.3×** on typed literals, +142 B | M |
| computed goto | −6 B | M |
| `UC_FOLD` accessors | −14 B (−22 B with computed goto) | M |
| `-Oz` vs `-Os` | **0 B** (byte-identical) | M |
| `-fno-jump-tables` | +88 B net | M |
| `-fno-builtin`, `-fno-stack-protector` | **0 B** | M |
| **P54** table-driven kernel, 10 same-shape primitives | `.text` −280, `.rodata` +56 = **pool −224 B**; dictionary byte-identical | M |
| **P54** shared tail for `msg()`/`errf` selection | **pool −52 B** (the win was a duplicated six-way selection, not the 20 call sites) | M |
| **P54** 3-byte headers + `wr8`/`wr16` pinned `noinline` | **−85 B of dictionary**, `.text` −8 B — the −8 is only real because the `noinline` pin holds it | M |
| **P54 rejected**: 1-byte tokens | ceiling **118 B** (tokens are only 236 B of the 578 B code area); prototype −44 B for **+352 B** | M |
| **P54 rejected**: merged rings | 64 + 128 B are already one contiguous 192 B block; a merge has **no array byte** to win | M |

## 8. Do not trust these two yet

| claim | why | what would settle it |
| --- | --- | --- |
| `BLKWAIT` wall-clock ≈0.2–0.4 s | derived from an iteration count, never timed | time a `BLOCK` that nobody answers, on the board |
| `memory` and `matrix` on the chip | they **fail**: `RES` writes 16 cells (64 B) and `,` has no dictionary bound, so it erased headers and `.` became unknown — see F-120 | more application space (a re-baked `image.h` at a larger `MEMSZ`), not more cycles |

The on-chip wall-clocks were on this list and are now measured for `arith` and `recursion` (P52, `rdcycle`
at the line boundary, cross-validated against the host dispatch counts to within 5 and 2 dispatches).

The `.text` / `.bss` split was on this list and has been removed: one `riscv32-esp-elf-size -A` on the current
ELF gives **5 252 / 308 / 1 216 / 1 077 = 7 853**, which is the same total the countdown reports. An
approximation in a reference file is a to-do, and this one was a single command away.

## 9. How to re-measure

```bash
# memory image (sections, exact)
cd probe/repl && export IDF_PATH=/home/user/research/esp32/esp-idf && . $IDF_PATH/export.sh
riscv32-esp-elf-size -A build/esp-idf/main/ulp_main/ulp_main.elf

# app space, straight from a fresh bake (prints "code N + headers M, free K")
./tools/bake.sh $(sed -nE 's/^#define MEMSZ +([0-9]+).*/\1/p' src/ulp_repl.c)

# pool headroom is enforced, not reported: this refuses to flash when over budget
./flash_safe.sh

# the acceptance surface (checksums + dispatch counts)
./bench/run.sh            # compare
./bench/run.sh --freeze   # re-baseline, deliberately

# the behavioural suite, including the storage semantics
tests/run.sh

# clock-derived constants (tick, dispatch cycles) come from the board, not the host:
#   probe/repl/probe-results/ holds the P42/P46 RESULT.md files with the raw cycle counts
```

## 10. Two bounds that are not where you expect

| bound | who enforces it | evidence |
| --- | --- | --- |
| header area vs code | **enforced** (`ERR_DICT`) | `image_boot_assert`, `PUSH_HDR` |
| `,` (append a cell) | **NOT enforced** | P52: 16 commas erased headers silently; `.` became unknown (F-120) |

The second is an open defect. Until it is fixed, "reserve a buffer with `,`" is only safe while the total
stays under the free application space — now **727 B**, which is why the `RES` workload that erased headers
at 154 B completes: measured on the board, 128 B of appends (two `RES`) followed by `2 3 + .` → **5**.

## 11. The shape of the constraint

7 853 of 7 856 bytes are spent. There are no free features left: every addition from here is a **trade**, and
the honest statement of the limit is that the machine is at **99.96 % utilisation** with **727 B** of program
space (4.7× the 154 B it shipped with), 1 KiB of RAM-backed block storage, 15 levels of recursion, and two
task slots.

The immutable part — 8 176 B, ~19 MHz, and no path from the coprocessor to flash, PSRAM or the main core's
512 KB — is the project's premise, not its obstacle.

## Overlay finding (measured, 2026): the toll is fixed and the window is the limit

Paging a program through the block store buys capacity only when every phase is near the window size (~690 B with
the event loop resident) and the program is well over 1.5 KB in total. Measured A/B: a control (same program, one
image, no overlays) has 1,536 B free and dies with `ERR_DICT`; the same program as six phases compiles to 1,608 B —
**+4 %** — while the manager and loop cost 846 B of resident space. The store is *not* the limit (six phases use 33
of 128 blocks, 26 %), and per-phase capacity is set by `LATEST HERE -` at the prompt, not by transport density. So
binary overlays, more blocks, or a denser encoding cannot move this: **overlays here are bounded by the window, the
window is bounded by RAM.** Do not retry paging on a small program; the overhead only pays for phases close to
window size.

Also: a block request that times out leaves `blk_out` latched, so every later block call answers `ERR_BUSY`. The
escape hatch is `0 2 BLKXFER` (op 2 = BLK_ABORT), which clears it without a reset. Naming that in the message costs
`.rodata` the pool cannot spare yet (3 B headroom); it is documented here instead.
