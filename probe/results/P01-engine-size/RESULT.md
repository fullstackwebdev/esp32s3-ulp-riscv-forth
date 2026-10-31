# P01 — Engine size and whether the resident budget closes

| | |
| --- | --- |
| Result | **PASS** (measured, reproducible) — the budget closes only at **2 page frames** |
| Route used | **IDF project** (`ulp_embed_binary`), verified by an independent direct link with the same flags |
| Target / toolchain | `esp32s3`, `riscv32-esp-elf-gcc 14.2.0 (esp-14.2.0_20241119)`, ESP-IDF v5.4 |
| `CONFIG_ULP_COPROC_RESERVE_MEM` | **8176** (the S3 maximum; see Finding F3) |
| Wall clock used | ~11 min of the 40 min box |
| Board | untouched — host only, nothing flashed |

Everything below is measured, not estimated. Commands are in §2; the artifacts they produce are in
`artifacts/`.

---

## 1. Answers

**Q: How many bytes is the engine?**

**3818 B** (3.73 KiB) of image — `.text` + `.rodata` — for the token interpreter, primitives,
parser/`FIND`/`NUMBER`, with `mem[]` excluded.

| | bytes |
| --- | --- |
| engine `.text` | 3556 (upper bound 3566) |
| engine `.rodata` (the 63-entry switch jump table) | 252 |
| engine `.data` | 0 |
| **engine image total** | **3808–3818** |
| engine `.bss` (not in the blob) | 222 (`ds` 64 + `rs` 64 + `tib` 80 + 14 B scalars) |
| platform startup (`ulp_riscv_vectors.S` + `start.S`) | 76 |
| stub (`pl_emit` 38 + `main` 8 + seed string 8) | 54 |
| `mem[MEMSZ]` at 2560 | 2560 (`.bss`, never in the blob) |
| **full ULP image `.bin` at MEMSZ 2560** | **3948** |

The headline is **3818 B**: it is `3948 − 130`, where 130 B is the stub-plus-startup content measured by
a control link (`--gc-sections` drops the engine when `main` does not call `interpret()`). That is an
over-estimate: `pl_key`/`pl_hw` are inlined into `main` and cannot be separated by symbol, so the true
engine is ~10 B smaller. The engine is therefore **3.73 KiB** — 1.2 KiB bigger than the 2600 B guess in
`01-proposal.md` §4.3, and above the 3.0 KiB threshold.

**Q: Does the §4.3 resident budget close with 4 page frames of 512 B?**

Barely, and not usefully — **560 B** left for a resident dictionary. With **2 frames** it is **1584 B**.

| Item | §4.3 estimate | measured / recomputed |
| --- | --- | --- |
| Engine (interpreter, primitives, parse/find/number) | ~2600 | **3818** |
| VM state + status + counters | 150 | 150 |
| Page frames 4 × 512 | 2048 | 2048 → **1024** at 2 frames |
| Page table + LRU | 200 | 200 |
| Forth stacks (data + return) | 400 | 400 (the engine's own 128 B is already inside this row) |
| Mailbox + cmd/out rings | 600 | 600 |
| C stack + guard band | 400 | 400 |
| **Subtotal** | **~6400** | **7616** at 4 frames / **6592** at 2 frames |
| Pool (S3 max RTC slow reservation) | ~8192 | **8176** (`CONFIG_ULP_COPROC_RESERVE_MEM` max) |
| **Remaining for resident dictionary** | **~1750** | **560** at 4 frames / **1584** at 2 frames |

The engine grew by 1218 B, which is 1.2 KB straight out of the dictionary. At 4 frames the prelude has
560 B; the honest reading is that the resident prelude does not fit there. At 2 frames 1584 B are left,
which is close to what §4.3 assumed all along.

**Answers to the specific measurement asks**

* `.text` / `.rodata` / `.data` / `.bss`, stub subtracted: table above (§2 has the raw `size -A`).
* `.bin`: **3948 B** at MEMSZ 2560, **3940 B** at MEMSZ 4096, **3944 B** at MEMSZ 2048.
* `MEMSZ` does **not** inflate the blob, but not for the reason the brief hoped: `.bss` tracks `MEMSZ`
  exactly (+512, +1536) while `.bin` moves by ≤8 B *downwards*, because the `a < MEMSZ` bound check in
  `P()` changes encoding (2048 fits the 12-bit signed branch immediate, 2560 and 4096 need a register
  compare). No array content reaches the blob. **The "array is `.bss`" assumption holds.**
* `nm` on the ULP ELF shows **no** Forth word symbols (R1 item 1, §3 F4).

**Two findings the brief did not ask for**

* **F3 — `MEMSZ` cannot be 4096 on this chip.** At `MEMSZ=4096` with the real 8176 B region the link
  fails: `address 0x2086 of ulp_main_memsz4096.elf section '.bss' is not within region 'ram'`. The
  engine (3948) + `mem[]` (4096) + stacks/state (290) = 8334 > 8176. The 4096 blob was therefore
  measured with the region length raised to 16384 in a copy of the linker script (`artifacts/ulp_riscv_bigregion.ld`);
  region length cannot affect `.bin`, and the invariant being tested holds either way. This is the same
  arithmetic as §1's table and it confirms it: the 8 KB pool is a hard wall, and 4096 B of Forth memory
  is not available to this design.
* **F5 — the engine inlines into one function.** All of `interpret`/`run`/`find`/`number`/`mkhdr` fold
  into `main` (2646 B) under `-Os`, so per-symbol sizes are uninformative and "subtract the stub's
  symbols" cannot work by symbol. A control link (`-DP01_STUB_ONLY`) was added to the stub for exactly
  this reason.

---

## 2. Evidence

### 2.1 Route

**IDF project** (`ulp_embed_binary`, the supported path), in `idfproj/`:

```
probe/results/P01-engine-size/
├── uforth.c              # verbatim copy; sha256 806e24cb1eb1d698b9284adc0504642b928135a94b2b484433b29d1174e423b6
├── ulp_stubs.c           # pl_key / pl_emit / pl_hw / main; #includes uforth.c (interpret() is static)
├── run_idf.sh            # the build driver (tmux + nice + timeout 900)
├── logs/idf_build.log    # full build log, ends with EXIT=0
├── idfproj/              # throwaway project: CMakeLists.txt, sdkconfig.defaults, main/
├── variants/             # MEMSZ 2048/4096 objects+ELFs, stub-only control, symbol dumps
└── artifacts/            # authoritative ulp_main.{elf,bin,map,sym,ld,h} + the above ELFs
```

The original `probe/uforth/uforth.c` was not modified (`sha256` of source and copy match). Nothing
outside `probe/results/P01-engine-size/` was written.

```
export IDF_PATH=/home/user/research/esp32/esp-idf && . $IDF_PATH/export.sh
cd probe/results/P01-engine-size/idfproj
timeout 300 nice -n 10 idf.py set-target esp32s3
timeout 900 nice -n 10 idf.py build
```

Artifacts land at `idfproj/build/esp-idf/main/ulp_main/ulp_main.{elf,bin,map,sym,ld}`, exactly as in
`probe/ulp_gpio`. The ULP compile line the supported path uses is the brief's line, verbatim:

```
riscv32-esp-elf-gcc -DIS_ULP_COCPU -DULP_RISCV_REGISTER_OPS <idf includes> \
  -Os -march=rv32imc_zicsr_zifencei -mdiv -fdata-sections -ffunction-sections \
  -c .../ulp_stubs.c -o .../ulp_stubs.c.obj

riscv32-esp-elf-gcc -march=rv32imc_zicsr_zifencei --specs=nano.specs --specs=nosys.specs \
  -nostartfiles -Wl,--gc-sections -Wl,--no-warn-rwx-segments -Wl,-Map=ulp_main.map \
  -T ulp_riscv.ld $IDF_PATH/components/ulp/ld/esp32s3.peripherals.ld -o ulp_main.elf <objs>
```

### 2.2 Authoritative build, MEMSZ 2560 (uforth default)

```
$ riscv32-esp-elf-size -A ulp_main.elf
section             size   addr
.text               3688      0
.rodata              252   3688
.srodata.seed.0        8   3940
.bss                2850   3948
.comment              47      0
.riscv.attributes     68      0
Total               6913

$ ls -l ulp_main.bin
3948

$ md5sum ulp_main.bin variants/ulp_main_memsz2560.bin
6ae0b048d94d67ea8f1255c5fd43f316  ulp_main.bin                        # IDF build
6ae0b048d94d67ea8f1255c5fd43f316  variants/ulp_main_memsz2560.bin     # independent re-link
```

The independent re-link uses the same flags lifted out of `build.ninja` and reproduces the IDF blob
byte for byte, so the recorded command line is sufficient on its own.

`.data` is 0 B: the engine keeps every byte of state in `mem[]` or in `.bss`.

### 2.3 Stub subtraction (control link)

Building the same stub with `-DP01_STUB_ONLY` (so `interpret()` is not called and `--gc-sections`
removes the whole engine) gives the stub's own floor:

```
$ riscv32-esp-elf-size -A variants/ulp_stub_only.elf
.text                 84      0        # main 8 + startup 76
.bss                   4     84        # ring_head

$ riscv32-esp-elf-nm --size-sort -S variants/ulp_stub_only.elf
00000054 00000004 b ring_head
00000014 00000008 T main
00000004 00000010 T __start
0000001c 00000014 T ulp_riscv_rescue_from_monitor
00000030 00000024 T ulp_riscv_halt
```

`pl_emit` (38) and the 8-byte seed string are collected in that control image, so the full stub
accounting is `84 + 38 + 8 = 130 B`, and the engine is `3948 − 130 = 3818 B`. `pl_key`/`pl_hw` are
inlined into `main` (≤ ~20 B, inside the 130), hence "3808–3818".

### 2.4 Ten largest symbols (authoritative ELF, `nm --size-sort -S`)

```
$ riscv32-esp-elf-nm --size-sort -S ulp_main.elf
00001a88 00000001 b errf
...
00001a7c 00000004 b ring_head
00000f64 00000008 r seed.0
00000004 00000014 T __start
00000e30 00000014 T ulp_riscv_rescue_from_monitor
000002c8 00000016 t a4
000000ec 0000001e t PUSH
0000010a 0000001e t RPUSH
00000286 00000020 t cw
00000018 00000020 t rd8
00000038 00000020 t wr8
000002a6 00000022 t clit
000000a6 00000022 t rd32
00000e44 00000024 T ulp_riscv_halt
00000082 00000024 t wr16
000000c8 00000024 t wr32
000002de 00000026 T pl_emit
00000058 0000002a t rd16
0000103c 00000040 b ds
00000f6c 00000040 b ring
00000ffc 00000040 b rs
00000304 00000042 t err
00000fac 00000050 b tib
000001f2 00000094 t find
00000346 00000094 t mkhdr
00000128 000000ca t word
0000107c 00000a00 b mem
000003da 00000a56 T main
```

| # | symbol | bytes | what it is |
| --- | --- | --- | --- |
| 1 | `main` | 2646 | the whole engine inlined (interpret + run + find + number + mkhdr) |
| 2 | `mem` (`.bss`) | 2560 | `mem[MEMSZ]`, not in the blob |
| 3 | `word` | 202 | outer-interpreter tokenizer |
| 4 | `find` | 148 | dictionary search |
| 5 | `mkhdr` | 148 | header construction |
| 6 | `tib` (`.bss`) | 80 | terminal input buffer |
| 7 | `err` | 66 | error echo |
| 8 | `ds` (`.bss`) | 64 | data stack |
| 9 | `rs` (`.bss`) | 64 | return stack |
| 10 | `ring` (`.bss`) | 64 | stub output ring (not engine) |

Because of F5 these per-symbol numbers rank almost nothing: the engine is one 2646 B function plus a
252 B jump table. For the structural breakdown the engine object was rebuilt with `-fno-inline`
(informational only — it is not the shipped build, and it is 1317 B larger because `-Os` inlining is
what keeps the interpreter small):

```
$ riscv32-esp-elf-nm --size-sort -S variants/uforth_noinline.o
00000000 00000040 b ds      00000000 00000040 b rs      00000000 00000050 b tib
00000000 00000062 t err     00000000 000000b2 t find    00000000 000000b2 t number
00000000 000000c8 t mkhdr_pad.constprop.0   00000000 000000dc t word
00000000 000000f2 T forth_quit    00000000 00000104 t interpret
00000000 00000a00 b mem     00000000 00000b60 t run
```

`run` is 2912 B of that — the 63-case primitive switch dominates, and the linked image's 252 B jump
table is its dispatch table. `forth_quit` (242) and `say` (34) are the char-at-a-time REPL and are
collected by `--gc-sections`, i.e. a design that feeds whole lines from the server does not pay them,
and a design that wants a local REPL pays ~276 B extra.

### 2.5 MEMSZ 2560 vs 4096 — the array stays in `.bss`

```
MEMSZ   .text  .rodata  .srodata  .data  .bss   .bin   mem[] in .bss
2048     3684     252        8       0    2338   3944   2048
2560     3688     252        8       0    2850   3948   2560
4096     3680     252        8       0    4386   3940   4096
```

```
$ diff <(riscv32-esp-elf-size -A obj/uforth_memsz2560.o) <(riscv32-esp-elf-size -A obj/uforth_memsz4096.o)
< .text.rd8                     36          > .text.rd8                     32
< .text.wr8                     36          > .text.wr8                     32
< .bss.mem                    2560          > .bss.mem                    4096
< Total                       7809          > Total                       9337
```

`.bss` deltas are exactly the `MEMSZ` deltas (+512, +1536). `.bin` moves by −8 B and −4 B, which is the
encoding of `a < MEMSZ` in `P()` (`li` vs immediate branch), not array content. **`MEMSZ` does not
inflate the blob.**

At `MEMSZ=4096` the link against the real region fails (finding F3):

```
ld: address 0x2086 of variants/ulp_main_memsz4096.elf section `.bss' is not within region `ram'
```

so the 4096 row was produced with `-T artifacts/ulp_riscv_bigregion.ld` (region `LENGTH = 16384`
instead of 8176). Region length is not in the blob; the `.bss`/`.bin` invariant is what was being
measured and it is unaffected.

### 2.6 R1 item 1 — no Forth word symbols in the ULP ELF

42 symbols total. Exact-name intersection of the ELF symbol table with the 36 word names defined by
`probe/uforth/boot_min.fs` (plus the primitive table's `DUP`, `SWAP`, `EXIT`, …), and with the
dictionary-entry symbols (`HEADER`, `LATEST`, `HERE`, `PAD`, `STATE`, `BASE`):

```
$ riscv32-esp-elf-nm ulp_main.elf | awk '{print $NF}' | sort -u > elf_symbols.txt
$ grep -oE "^: [^ \t]+|^[A-Z0-9_.+<>?=*/-]+ +CONSTANT" probe/uforth/boot_min.fs | awk '{print $2}' | sort -u > prelude_words.txt
$ comm -12 prelude_words.txt elf_symbols.txt
$                       # empty
```

**No** prelude word, no header, no Forth name of any kind is in the image: the only symbols are C
functions/variables and the two RISC-V startup stubs. The engine contains no user words — R1's first
acceptance item holds on the host side. (`strings -a ulp_main.bin` shows binary noise plus the stub's
seed `12 34 +` and no dictionary text at all.)

---

## 3. Verdict

**PASS.** The engine is measured and reproducible: **3818 B** (3.73 KiB) of image at
`-Os -march=rv32imc_zicsr_zifencei -mdiv -fdata-sections -ffunction-sections`, `.data` 0 B,
222 B of `.bss` besides `mem[]`.

Applying the brief's failure criteria in order:

* engine **3818 > 3072 (3.0 KiB)** ⇒ §4.3 switches to **2 frames (1 KiB)**; the dictionary gains 1 KiB.
  New table: subtotal **6592 B**, **1584 B** for the resident dictionary.
* engine **3818 < 4096 (4.0 KiB)** ⇒ **not** the §12 stop condition. The resident design still closes,
  but only at 2 frames.

Consequences to carry forward:

1. §4.3's `~2600` engine row was **1.2 KiB optimistic**. Everything else in the budget was a guess with
   the same risk; the remaining rows (150/200/400/600/400) are still unmeasured and 8 KB is the hard
   ceiling (F3).
2. 4 frames leaves 560 B, which is not a resident dictionary. The 2-frame decision is forced by
   measurement, exactly as §4.3 pre-declared — the knob was defined, not re-invented here.
3. There is **no room to absorb another 1.2 KB surprise**: at 2 frames the design has 1584 B of slack in
   an 8176 B pool whose engine alone is 3818 B. The next probe should measure what the prelude actually
   costs resident before any more design work leans on that 1584.

Limits of this result, stated plainly: the image was **linked and measured, never executed** (host-only
probe; the ULP binary was not run, and the seed line `12 34 +` exists only to put `interpret()` on the
call graph). `SD=16`, `TIBSZ=80` are the uforth defaults, unmodified. Stack usage at runtime is therefore
not measured, and the "C stack + guard band 400" row is still an estimate.

---

## 4. Doc deltas

Hand-back text, ready to paste. (No file under `docs/` was edited by this probe.)

### 4.1 `docs/01-proposal.md` §4.3

Replace the engine row

```
| Engine (interpreter, primitives, parse/find/number) | ~2600 |
```

with

```
| Engine (interpreter, primitives, parse/find/number) | 3818 (measured, P01: `.text` 3556 + `.rodata` 252, `mem[]` excluded) |
```

Replace the table's closing rows

```
| **Subtotal** | **~6400** |
| Remaining for resident dictionary (the interpreted prelude lives here) | **~1750** |
```

with

```
| **Subtotal** | **6592** (2 frames) / **7616** (4 frames) |
| Remaining for resident dictionary (the interpreted prelude lives here) | **1584** (2 frames) / **560** (4 frames) |
```

and replace the sentence

```
If the measured engine exceeds 3.0 KB, the frame count drops to 2 (1 KB) and the dictionary gains
1 KB. That is the only knob; it is decided by a build, not by taste.
```

with

```
The engine measured 3818 B on the ULP toolchain (P01, `probe/results/P01-engine-size/RESULT.md`),
above the 3.0 KB threshold, so the frame count is **2 frames of 512 B** and the dictionary keeps
1 KB more than the 4-frame layout would leave it: **1584 B** of the 8176 B pool, against 560 B at
4 frames. That is the only knob and it is now decided by a build, not by taste. The pool is hard:
`CONFIG_ULP_COPROC_RESERVE_MEM` cannot exceed 8176 B on the S3, and engine + frames + dictionary
+ stacks must all fit inside it.
```

Also correct the pool row if one is added: it is **8176 B** (`CONFIG_ULP_COPROC_RESERVE_MEM` maximum),
not 8192 — the 16 B difference is why the numbers above are 8176-based.

### 4.2 `docs/00-background.md` C11 row

Replace the C11 row

```
| C11 | "Forth core in RV32C 2.5–3.5 KB" | plausible but unmeasured; it is a *target*, not a fact | measured by the first ULP build (Q3 in `01-proposal.md`) |
```

with

```
| C11 | "Forth core in RV32C 2.5–3.5 KB" | measured at the top of the range: **3818 B** `.text`+`.rodata` for token interpreter, primitives and parser (`mem[]` excluded, `.data` 0, 222 B `.bss`) | P01, `probe/results/P01-engine-size/RESULT.md`; E-007 |
```

### 4.3 `probe/EVIDENCE.md` — new entry

```
## E-007 — engine size 3818 B, and the 4-frame budget does not close

Built the prototype engine (`probe/uforth/uforth.c`, copied verbatim, sha256 `806e24cb…e423b6`) with the
IDF ULP-RISC-V path (`ulp_embed_binary`, `esp32s3`, `CONFIG_ULP_COPROC_RESERVE_MEM=8176`) plus a stub
providing `pl_key`/`pl_emit`/`pl_hw` and a `main` that seeds the input buffer and calls `interpret()`.

Artifacts: `probe/results/P01-engine-size/idfproj/build/esp-idf/main/ulp_main/ulp_main.{elf,bin,map}`,
copied to `probe/results/P01-engine-size/artifacts/`.

```
text 3688  rodata 252  srodata 8  data 0  bss 2850   (MEMSZ 2560)
bin 3948 B  (md5 6ae0b048d94d67ea8f1255c5fd43f316, reproduced by an independent re-link)
stub + startup 130 B (control link with -DP01_STUB_ONLY, engine collected by --gc-sections)
→ engine 3818 B = 3556 text + 252 rodata, .data 0, .bss 222 (ds 64 + rs 64 + tib 80 + 14 scalars)
```

`MEMSZ` does not inflate the blob: `.bss` tracks it exactly (2338 / 2850 / 4386 for 2048 / 2560 / 4096)
while `.bin` moves by ≤8 B *down* (3944 / 3948 / 3940), from the `a < MEMSZ` bound-check encoding.
`MEMSZ=4096` does not even link against the real 8176 B region (`address 0x2086 … not within region
'ram'`; engine + 4096 + 290 > 8176), so 4096 B of Forth memory is not available to this design.

Recomputed §4.3: subtotal 7616 B at 4 × 512 B frames → 560 B for the resident dictionary; 6592 B at
2 frames → 1584 B. Engine 3818 > 3.0 KB ⇒ 2 frames (per the pre-declared rule); < 4.0 KB ⇒ no stop
condition.

`nm` on the ELF shows 42 symbols, all C or RISC-V startup; intersecting with the 36 word names in
`boot_min.fs` and with `HEADER`/`LATEST`/`HERE`/`PAD`/`STATE`/`BASE` yields the empty set — R1 item 1
holds (the engine contains no user words, and the blob carries no dictionary text).

Command:
```
export IDF_PATH=/home/user/research/esp32/esp-idf && . $IDF_PATH/export.sh
cd probe/results/P01-engine-size/idfproj && timeout 300 idf.py set-target esp32s3 && timeout 900 idf.py build
```
```

---

## 5. Follow-ups

1. **P-new: cost of the resident prelude.** 1584 B is the whole remaining budget at 2 frames. Build
   `boot_min.fs` into an image and measure `V_HERE − DICT` — that is the number §4.3 actually needs and
   it is not measured anywhere yet.
2. **Measure the other five budget rows.** 150/200/400/600/400 are still guesses summing to 1750 B
   against 1584 B of slack. A 4-frame layout that must survive a 1.2 KB surprise cannot be built on
   guesses; the mailbox ring and C-stack rows are the ones most likely to be wrong.
3. **Re-check the 8 KB wall.** F3 shows engine + `mem[]` + stacks overflow the 8176 B region at
   `MEMSZ=4096`. Whatever `MEMSZ` becomes in the design, it has to be re-linked against the real region
   limit, not just measured as a `.bin`.
4. **Decide whether a local REPL exists.** `forth_quit` + `say` cost ~276 B and are collected today
   because nothing calls them. If the ULP keeps a char-at-a-time REPL, add 276 B to the engine and
   subtract it from the dictionary headroom.
5. **Runtime stack depth is unmeasured.** `ds`/`rs` are `SD=16` cells (128 B); `P01` never executed the
   image. If `SD` has to grow, it comes out of the same 8176 B pool.
