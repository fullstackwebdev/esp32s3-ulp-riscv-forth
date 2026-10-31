# P12 — Engine cost at 32-bit references with 4 × 256 B frames

| | |
| --- | --- |
| Result | **PASS** (measured, reproducible) — engine **3986 B**, +168 B (+4.4 %) vs P01; frames + table cost **0 B** of `.bin`; **but the §4.3 spare does not survive** at 32-bit: it is **−266 B**, not 440 B |
| Route used | the P01 recipe, unchanged: ESP-IDF `ulp_embed_binary` project, stub subtraction (`-DP01_STUB_ONLY`), same flags |
| Target / toolchain | `esp32s3`, `riscv32-esp-elf-gcc 14.2.0 (esp-14.2.0_20241119)`, ESP-IDF v5.4 |
| `CONFIG_ULP_COPROC_RESERVE_MEM` | 8176 (S3 maximum, as in P01) |
| Sources | `uforth.c` = **P02's 32-bit variant** (`sha256 0e4de02a…34088`, `probe/results/P02-token-width/b32/uforth.c`), + paging added here |
| Wall clock used | ~16 min (configure overlapped with the code edit; build 1050 steps, `EXIT=0`) |
| Board | untouched — host only, nothing flashed, no serial device opened |

Everything below is measured from `artifacts/ulp_main.{elf,bin,map}`.

---

## 1. Answers

**Q: What does the engine cost at 32-bit references with 4 × 256 B frames?**

**3986 B** of image (`.text` + `.rodata`), `mem[]` excluded — **+168 B (+4.4 %)** over P01's 3818 B.

| | bytes |
| --- | --- |
| engine `.text` (stub subtracted) | 3734 |
| engine `.rodata` (63-entry switch jump table) | 252 |
| **engine image total** | **3986** |
| engine `.data` | **0** (no `.data` section exists in the ELF) |
| engine `.bss` (not in the blob) | 2782 = `mem` 2560 + `ds`/`rs`/`tib`/scalars 222 |
| 4 × 256 B frames + 4-entry page table (`frm`, `ptab`) | **1040 in `.bss`, 0 in `.bin`** |
| platform startup (`ulp_riscv_vectors.S` + `start.S`) | 76 |
| stub (`pl_emit` 38 + `main` 8 + seed string 8 → with startup: 130) | 130 |
| **full ULP image `.bin` at `MEMSZ` 2560** | **4116** |
| `.bin` at `MEMSZ` 2048 / 4096 | 4112 / 4108 |

`4116 − 130 = 3986`, using the identical control link P01 used (`-DP01_STUB_ONLY`, engine collected by
`--gc-sections`; the stub floor is `.text` 84 = startup 76 + `main` 8, plus `pl_emit` 38 and the 8-byte
seed string that the control image does not contain).

**Q: Do the 4 frames and the page table inflate `.bin`?**

**No — 0 bytes.** Three independent checks, all in §2.3:

1. `.bin` is exactly `.text + .rodata + .srodata` (3856 + 252 + 8 = 4116) and there is **no `.data`
   section** in the ELF at all;
2. `nm` types both arrays `b` (`.bss`): `frm` 1024 B, `ptab` 16 B;
3. `.bss` compared with P01's is **+1040 B exactly** — 1024 + 16, nothing else moved (`mem[]` is still
   2560 at both `MEMSZ`, P01's row).

**Q: Does the §4.3 budget still close, and what spare is left?**

No. The table recomputes to a **1416 B** dictionary headroom, which is **less than the 32-bit
dictionary needs** — the spare is negative, so resolution A (a resident prelude) is insufficient.

| Item | §4.3 estimate | P01 (16-bit) | **P12 (32-bit + paging, measured)** |
| --- | --- | --- | --- |
| Engine | ~2600 | 3818 | **3986** |
| VM state + status + counters | 150 | 150 | 150 |
| Page frames 4 × 256 | 1024 | (4 × 512 = 2048) | **1024** |
| Page table + LRU | 200 | 200 | 200 |
| Forth stacks (data + return) | 400 | 400 | 400 |
| Mailbox + cmd/out rings | 600 | 600 | 600 |
| C stack + guard band | 400 | 400 | 400 |
| **Subtotal** | **~5374** | **7616** | **6760** |
| Pool (S3 max RTC slow reservation) | ~8192 | 8176 | **8176** |
| **Headroom for the resident dictionary** | **~1750** | 560 | **1416** |
| less 48 B line buffer | | | **1368** |
| Resident dictionary, §4.3's 16-bit figure (1096 B) | 1096 | | 1096 → spare **272** |
| Resident dictionary at P02's measured 32-bit cost (1096 × 1.49 = 1634) | | | 1634 → **spare −266** |

**The number to carry forward: spare = −266 B** (1368 − 1634). The 16-bit row is kept only to show
that even the *favourable* reading (272 B) needs the dictionary to ignore P02's 1.49× measurement,
which it cannot. Cross-check with P02's directly measured boot-layer dictionary: **1956 B** at 32-bit,
which leaves 1368 − 1956 = **−588 B**. Either way the sign is negative, so the brief's first failure
criterion fires: *spare < 150 B ⇒ resolution A is insufficient.*

**Q: Does the engine trip the §12 stop condition (4.2 KB)?**

No. 3986 B = 3.89 KiB, i.e. 316 B below 4300. The 32-bit width change itself costs almost nothing in
*code*; nearly all of the +168 B is the paging machinery (§2.4).

---

## 2. Evidence

### 2.1 Route and commands

The P01 project was copied wholesale — same `idfproj/{CMakeLists.txt,sdkconfig.defaults,main/}`, same
`ulp_stubs.c`, same `-DP01_STUB_ONLY` control. Only `project()` was renamed (`p12_engine_32bit`) and
`uforth.c` was replaced with P02's 32-bit variant before the first build.

```
export IDF_PATH=/home/user/research/esp32/esp-idf && . $IDF_PATH/export.sh
bash probe/results/P12-engine-32bit/prep_idf.sh        # idf.py set-target esp32s3, logs/prep.log, EXIT=0
bash probe/results/P12-engine-32bit/run_idf_p12.sh     # idf.py build, logs/idf_build.log, EXIT=0
python3 probe/results/P12-engine-32bit/variants.py     # control link + MEMSZ variants, logs/variants.log
```

Both builds ran in tmux under `timeout 300 nice -n 10`, output redirected to `logs/`. The build log is
1050 steps, ends `EXIT=0`, and contains **zero** `warning:` / `error:` lines.

### 2.2 Authoritative image, `MEMSZ` 2560 (uforth default)

```
$ riscv32-esp-elf-size -A artifacts/ulp_main.elf
section             size   addr
.text               3856      0
.rodata              252   3856
.srodata.seed.0        8   4108
.bss                3890   4116
.comment              47      0
.riscv.attributes     68      0
Total               8121

$ stat -c %s artifacts/ulp_main.bin
4116
$ md5sum artifacts/ulp_main.bin idfproj/build/esp-idf/main/ulp_main/ulp_main.bin
c045d083530d71daf3c0ecde6ab5f544  artifacts/ulp_main.bin
c045d083530d71daf3c0ecde6ab5f544  idfproj/build/esp-idf/main/ulp_main/ulp_main.bin
```

`.data` is 0 B: no `.data` section is emitted, so there is nothing to copy from flash at boot.

### 2.3 Stub subtraction and the frames/table proof

```
$ riscv32-esp-elf-size -A variants/ulp_stub_only.elf
.text                 84      0        # main 8 + startup 76
.bss                   4     84        # ring_head
$ stat -c %s artifacts/ulp_stub_only.bin
84
```

`pl_emit` (38) and the seed string (8) are collected in that control image, so the stub floor is
`84 + 38 + 8 = 130` and the engine is `4116 − 130 = 3986` — the identical accounting P01 used.

The 1040 B of frames + table:

```
$ riscv32-esp-elf-nm artifacts/ulp_main.elf | grep -E ' (frm|ptab|mem)$'
00001134 b frm          # 00000400 = 1024 B, type b (bss)
00001124 b ptab         # type b (bss), 16 B
00001534 b mem          # 00000a00 = 2560 B
```

`.bss` attribution, P01 → P12: `2850 → 3890` = **+1040 = 1024 (`frm`) + 16 (`ptab`)**, with `mem[]`
unchanged at 2560. `.bin` attribution: `3948 → 4116` = **+168**, all of it `.text`(+168)/`.rodata`(±0);
nothing in the blob comes from the arrays. **Frames + table cost 0 B of `.bin`.**

`MEMSZ` sweep (same link flags, `variants.py`; the 4096 row uses P01's `ulp_riscv_bigregion.ld`,
region `LENGTH = 16384`, because the real 8176 region cannot hold it — P01 F3):

| `MEMSZ` | `.text` | `.rodata` | `.srodata` | `.data` | `.bss` | `.bin` | `.bin` + `.bss` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2048 | 3852 | 252 | 8 | 0 | 3378 | 4112 | 7490 |
| 2560 | 3856 | 252 | 8 | 0 | 3890 | **4116** | **8006** |
| 4096 | 3848 | 252 | 8 | 0 | 5426 | 4108 | 9534 |

`.bss` deltas are exactly the `MEMSZ` deltas (+512, +1536) and `.bin` moves *down* by 4–8 B (the `a <
MEMSZ` compare encoding inside `P()`), exactly as in P01. Two consequences worth carrying:

* at `MEMSZ` 2560 the whole image plus all `.bss` is **8006 of 8176** — only **170 B** of RTC-region
  slack, before any VM state is placed;
* at `MEMSZ` 4096 — the value P02 says 32-bit xts need for boot + corpus — the footprint is **9534 B,
  i.e. 1358 B over the pool**. The 4096 blob only links with a widened region, so **the 8 KB pool
  cannot hold a 32-bit-xt engine with 4 KB of Forth memory**: 2560 remains the only `MEMSZ` that links.

### 2.4 Biggest contributors to the +168 B

```
$ riscv32-esp-elf-nm --size-sort -S artifacts/ulp_main.elf
00000476 00000a62 T main        # 2658 (P01: 2646, +12)
000001da 000000ca t word        #  202 (unchanged)
000003e6 00000090 t mkhdr       #  144 (P01: 148)
000002a4 0000008c t find        #  140 (P01: 148)
000000ec 0000006c t pg_load     #  108  new: stub page-in
00000158 00000046 t rd32_paged  #   70  new: paged instruction fetch
0000019e 0000001e t PUSH        #   30
```

| # | symbol | bytes | contribution |
| --- | --- | --- | --- |
| 1 | `pg_load` | 108 | new — page-table probe + frame refill loop |
| 2 | `rd32_paged` | 70 | new — `rd32` through `resolve()` |
| 3 | `main` | 2658 | +12: the call sites inline, the token fetch becomes a call + the `cf`/`ip` fetch pair |
| 4 | `find` / `mkhdr` | 140 / 144 | −8 / −4: 32-bit cells drop the `rd16`+shift pairs at three places |
| 5 | `.rodata` | 252 | unchanged — the switch jump table is the same 63 cases at either width |

So the +168 B is **paging, not width**: paging helpers account for 178 B of new `.text`, the width
change is worth roughly −10 B of code, and the two cancel into +168. **The 32-bit reference width is
nearly free in the engine; the page frame machinery is what costs.** That is the opposite of what the
brief feared, and it is why the dictionary (1.49×, P02) rather than the engine is what kills the spare.

### 2.5 What was added to `uforth.c` (only this)

* `frm[4][256]` (1024 B) and `ptab[4]` (16 B) — uninitialised statics, i.e. `.bss`;
* `pg_load(pg)` — table probe, frame-0 refill from `mem[]`; no LRU and no dirty write-back, and it
  never faults (nothing is executed: the image is linked and measured, per the brief);
* `resolve(va)` → `&frm[pg_load(va / 256)][va % 256]`;
* `rd32_paged(va)` / `rd8_paged(va)` and the fetch-path call sites in `run()`: the code-field fetch
  (`cf`), the next-token fetch (`w`), `P_LIT`'s inline operand, `P_BRANCH`, `P_ZBRANCH`, `P_LOOP`'s
  target and `P_PDOTQ`'s string bytes. Data reads (`find`, headers, `P_DOVAR`/`P_DOCON` bodies) still
  use `rd32` — they address `mem[]` through `P()` and are not instruction fetches.

Nothing else in the engine was touched: no optimisation, no inlining change, no feature removal.

---

## 3. Verdict

**PASS on the measurement; the design answer is bad news for §4.3.**

* Engine at 32-bit xts + paging: **3986 B** (`.text` 3734 + `.rodata` 252), **+168 B / +4.4 %** vs
  P01's 3818 B; `.bin` **4116 B** at `MEMSZ` 2560; `.data` 0 B. Measured with P01's exact recipe, so the
  two numbers are directly comparable.
* Frames + page table are **free in `.bin`** (0 B) and 1040 B of `.bss` — the brief's `.bss` assumption
  holds, proved three ways (§2.3).
* The engine is **316 B under** the 4.2 KB §12 stop condition, so no stop is triggered.
* **The §4.3 spare does not survive.** Headroom for the resident dictionary is **1368 B** after the
  48 B line buffer; a 32-bit dictionary of the same word count needs **1634 B** (P02's measured 1.49×),
  so the spare is **−266 B** (−588 B against P02's directly measured 1956 B boot layer). Resolution A
  as written is **insufficient**: the prelude itself must be paged, with only the hot core resident,
  and the "first `WORDS` may fault" concession becomes "most of the standard vocabulary may fault".
* Unasked-for finding: the 32-bit design has **no room for `MEMSZ` 4096** (9534 B footprint vs the
  8176 pool), so the two changes P02 says it needs — 32-bit xts and ≥ 4 KB of Forth memory — cannot
  both be paid for out of the 8 KB RTC pool at this engine size.

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
| Engine (interpreter, primitives, parse/find/number) | 3986 (measured, P12: `.text` 3734 + `.rodata` 252, `mem[]` excluded, 4 × 256 B frames and the page table included) |
```

Replace the table's closing rows

```
| Subtotal | ~6400 |
| Pool (S3 max RTC slow reservation) | ~8192 |
| **Remaining for resident dictionary** | **~1750** |
```

with

```
| Subtotal | 6760 |
| Pool (S3 max RTC slow reservation) | 8176 |
| **Remaining for resident dictionary** | **1416** (1368 after the 48 B line buffer) |
```

and replace the spare sentence

```
The resident dictionary needs ~1096 B, leaving ~440 B of spare.
```

with

```
The resident dictionary needs ~1096 B at 16-bit cells; at the adopted 32-bit xts it needs 1634 B
(P02: 1.49×). Against the measured P12 headroom of 1416 B — 1368 B after the 48 B line buffer — the
spare is **−266 B**: the prelude does not fit resident. Only the hot core stays, and the rest of the
standard vocabulary is paged, so "the first `WORDS` may fault" becomes "most of the standard
vocabulary may fault". P12 also measures the whole image + `.bss` at 8006 of the 8176 B pool at
`MEMSZ` 2560, so `MEMSZ` cannot rise to the 4096 that 32-bit xts want (footprint 9534 B).
```

### 4.2 `probe/EVIDENCE.md` — new entry under E-010

```
### E-010 (P12 addition) — engine at 32-bit references with 4 x 256 B frames: 3986 B (P12)

`probe/results/P12-engine-32bit/` (host only; P01's IDF project and `-DP01_STUB_ONLY` control link,
P02's 32-bit `uforth.c`, plus `frm[4][256]` + `ptab[4]` and the paged fetch path).

* engine `.text` 3734 + `.rodata` 252 = **3986 B**, `.data` 0, engine `.bss` 2782, full `.bin`
  **4116** at `MEMSZ` 2560 (`4116 - 130` stub = 3986).
* **+168 B / +4.4 %** vs P01's 3818 B, and 316 B below the 4.2 KB §12 stop condition.
* Frames + page table cost **0 B of `.bin`**: no `.data` section, `nm` types them `b`, `.bss` grows by
  exactly 1040 B (1024 + 16) with `mem[]` unchanged.
* The +168 is paging, not width: new `pg_load` 108 + `rd32_paged` 70 = 178 B of helpers.
* §4.3 recomputed: headroom 1416 B, **1368** after the 48 B line buffer; a 32-bit dictionary needs
  1634 B (1096 × P02's 1.49) ⇒ **spare −266 B** (or −588 B against P02's measured 1956 B boot layer).
  Resolution A is insufficient: the prelude is paged, not resident.
* Extra: the full image + `.bss` is 8006 B of the 8176 B pool at `MEMSZ` 2560; at `MEMSZ` 4096 it is
  9534 B, so 32-bit xts and ≥ 4 KB of Forth memory cannot both be paid for.
```

---

## 5. Follow-ups

1. **The dictionary, not the engine, is the budget problem.** §4.3 must stop treating the prelude as
   resident. Cheapest lever: P02's 1.49× is header-heavy (44 % of the dictionary is headers, 39.2
   B/word against 21–32 for boot-layer words), so a header-compression or name-elision pass buys more
   spare than anything in the interpreter.
2. **`MEMSZ` decision is unresolved and now blocking.** 2560 links (170 B of region slack); 4096 does
   not. P02's "raise `MEMSZ` to ≥ 4096" and the 8 KB pool are in direct conflict; one of the two has
   to give.
3. `pg_load` here is a stub with a fixed victim and no write-back. A real P03e implementation adds
   dirty tracking and an LRU — expect a **small further growth** (est. 100–150 B) that this probe does
   not include; the spare is negative even without it.
4. Not measured: the 32-bit interpreter's speed. P05's 19 MHz / 8.1 cycles per word figure predates
   paging; every fetch now costs a `resolve()` (divide by 256, table probe, modulo), so P05 needs a
   re-run before R5 quotes a number.
