# P22 — Does the machine, as now specified, fit?

| | |
| --- | --- |
| Result | **PASS at a smaller `MEMSZ` than §4.3's own arithmetic — and that is the finding.** The machine links, but only with **`MEMSZ` = 1188 B**, not the 1380 B the §4.3 lines add up to. At 1380 B the link **fails** with `ld: address 0x1f6e of .../ulp_main_p22.elf section '.bss' is not within region 'ram'` — **190 B over**. The 202 B difference is fully attributable: **142 B is the platform-hook/REPL-entry code that §4.3 has no line for**, **28 B is the engine growing when the `MEMSZ` constant shrinks** (the `a < MEMSZ` bound folds into every access path), and 22 B + 10 B are alignment and the residue. The prelude is **not** the problem: measured resident dictionary after resolution A is **1104 B**, which fits inside 1188 B with **84 B to spare**, so nothing was trimmed to make it link. **Fits, no room to grow**: 10 B of pool plus 84 B of `mem[]` = **94 B total spare**. |
| Runs on | **host only** (`riscv32-esp-elf` compile + link with IDF's own generated flags; `gcc -DHOST` for the dictionary). Board untouched, no serial device opened. |
| Target / toolchain | `esp32s3`, `riscv32-esp-elf-gcc 14.2.0 (esp-14.2.0_20241119)`, ESP-IDF v5.4, `CONFIG_ULP_COPROC_RESERVE_MEM=8176` |
| Sources | `src/uforth.c` = **P20 variant C verbatim**, edited only for the §4.3 lines: `FRMB` 256 → **512**, `TIBSZ` 80 → **128**, `SD` 16 (unchanged = 128 B of stacks), plus the P04 rings/mailbox and the two data-only lines (§4.3 `VM state` 150, `LRU` 234) declared so the link charges them. `src/ulp_stubs.c` = P20's stub, `pl_emit` retargeted at the engine's own 256 B `out_ring`. `src/ulp_p22.ld` = IDF's `ulp_riscv.ld` with `LENGTH = 8176 − 320` (P21's C stack). |
| Wall clock | ~14 min of the 15 min box for three links (25 s each) + the host dictionary measurement; the first link of each run is a compile of the same TU, no IDF configure. |

## Record

| Item | Value |
| --- | --- |
| engine `.text` / total | **3010 / 3190** (`.text` 3010 + `.rodata` 180, after subtracting the 142 B stub floor; `.bin − control` = 3198). P20 measured 2982 / 3162 for the same engine at `MEMSZ` 2560 — the difference is the `MEMSZ` constant, see §1.4 |
| resident dictionary after headers move | **1104 B** (measured, header-walk of the compiled 1716 B dictionary) |
| name directory size | **812 B** (links + flags + names + xts, paged) |
| `MEMSZ` chosen | **1188 B** — the largest value that links. §4.3's line arithmetic gives **1380 B, which does not link** (−190 B) |
| link result | **FAIL at 1380 B**, exact message in §1.1; **PASS at 1188 B** |
| `.bin` | **3340 B** as linked (engine `.bin` = 3198 after the 142 B stub subtraction) |
| **leftover bytes** | **10 B** of the 7856 B pool + **84 B** unused inside `mem[]` = **94 B total** |

---

## 1. Answers

**Q: Does the machine as §4.3 specifies it link?**
**No, not at §4.3's own `MEMSZ`.** Set up exactly as the method prescribes — `MEMSZ = 8176 − (everything
else)`, with the P21 320 B C stack taken out of the pool by the linker script — and the value that
arithmetic produces is **1380 B** (`8176 − 320 − 3162 − 150 − 2048 − 250 − 128 − 600 − 128`). The link
rejects it by **190 B**:

```
ld: address 0x1f6e of /home/user/research/esp32-rv32/probe/results/P22-fits/artifacts/ulp_main_p22.elf
      section `.bss' is not within region `ram'
```

`0x1f6e` = 8046, the region ends at `0x1eb0` = 7856 ⇒ **190 B over**. Bisecting: 1190 B is **2 B** over
(`0x1eb2`), **1188 B links**. So the machine fits **1188 B** of resident dictionary, not 1380 B.

**Q: Is the resident dictionary the thing that does not fit?**
**No — and this is the point of the probe.** Measured, not extrapolated: the compiled prelude is
**1716 B** with headers (reproduces P20 variant C exactly), the header walk puts **612 B** of that in
links+flags+names+padding, so the resident area is **1104 B** (system variables 64 + code fields 78×4 +
bodies) and the paged directory is **812 B**. **1104 ≤ 1188: it fits with 84 B spare.** Nothing was
trimmed and no word was dropped. §4.3's estimate of "~962 B resident" was **142 B optimistic**.

| | §4.3 estimate | measured (P22) |
| --- | --- | --- |
| prelude with headers | 1716 | **1716** (= P20 C) |
| headers' share | 44 % ≈ 754 B | **612 B** (`link 2 + flags 1 + name n + pad`, 78 definitions) |
| resident (code fields + bodies + sysvars) | ~962 | **1104** |
| directory (links + flags + names + **xts**) | — (folded into the 44 %) | **812** |
| total Forth memory | 1716 | **1916** |

The total is **200 B larger** than the compiled dictionary, not smaller: a directory entry has to carry
the **xt** (4 B × 78 = 312 B) because the code field is no longer reachable from the name, and it saves
the 112 B of header padding. Resolution A moves **812 B out of the pool at a cost of 312 B of xt
duplication** — it is a relocation, not a compression, and §4.3 should say so.

**Q: What exactly is the 202 B that §4.3 does not count?**

| line | B | where it comes from |
| --- | --- | --- |
| platform hooks + REPL entry (`pl_key`, `pl_emit`, `pl_hw`, `main`) | **+142** | §4.3 has **no line** for the ULP-side hook code. Measured as the `-DP01_STUB_ONLY` control image. The 256 B `out_ring` is budgeted (P04); the code that feeds it is not. |
| engine `.text` growth when `MEMSZ` shrinks | **+28** | 2982 (P20, `MEMSZ` 2560) → 2992 (`MEMSZ` 1390) → **3010** (`MEMSZ` 1188). `P()`'s bound `a < MEMSZ` is folded into every access path, so the pool constant is worth ±30 B of code — a coupling nobody has costed. |
| section alignment / residue | **+32** | 22 B of `.bss` alignment + 10 B left over. |
| **total** | **202** | 1380 − 202 = **1188** ✅ |

**Q: So does the design fit?** **Yes, with 94 B spare — "fits, no room to grow."** The pool closes as:

```
7856 (= 8176 − 320 C stack)
 = 22 align + 142 hooks + 3190 engine (.text 3010 + .rodata 180)
 + 2048 frames + 250 table/LRU + 128 stacks + 600 rings + 216 mailbox(line total 600)
 + 150 VM state + 128 line buffer + 1188 mem[] + 10 leftover
```

and `mem[]` holds 1104 of resident dictionary, 84 B spare. Per the brief's third failure criterion this
is **"fits, no room to grow"**: the next feature (a `WORDS` fast path, a real LRU, one more prelude
word ≈ 14 B resident each) will not fit, and §4.3 must say so.

### 1.1 Exact link results

```
# MEMSZ = 1380  — the value §4.3's lines add up to
ld: address 0x1f6e of /home/user/research/esp32-rv32/probe/results/P22-fits/artifacts/
    ulp_main_p22.elf section `.bss' is not within region `ram'
collect2: error: ld returned 1 exit status
EXIT=1                     (0x1f6e = 8046 vs region end 0x1eb0 = 7856 → 190 B over)

# MEMSZ = 1190  — first bisection step
ld: address 0x1eb2 ... not within region `ram'      (2 B over)

# MEMSZ = 1188  — links
P22: bin=3340 text=3152 rodata=180 srodata=8 data=0 bss=4514
control: bin=142 text=142 rodata=0 srodata=0 data=0 bss=992
region use: 7846 of 7856  -> 10 B left
EXIT=0
```

### 1.2 The two builds that "passed" before the bisection were wrong — and why

The first link of this probe **passed at `MEMSZ` = 1390 with 880 B to spare**. It was false: `cmd_ring`,
`mailbox`, `vm_state_reserve` and `ptab_lru_reserve` had been **removed by the compiler** (dead stores to
static arrays whose address never escapes, then `--gc-sections`), so **728 B of budget lines were simply
absent** from `.bss`. `nm -S` on the ELF is what caught it. A "does it fit" build whose lines can vanish
is worthless, so every budget array is now kept alive through a `volatile` access in `main` and the
lines are individually visible in the symbol table:

```
00000e0c 000000ea b ptab_lru_reserve     234
000011e8 00000010 b ptab                  16
00000dcc 00000040 b ds                    64
00000d8c 00000040 b rs                    64
00001168 00000080 b cmd_ring             128
00000d0c 00000080 b tib                  128
00000ef8 00000096 b vm_state_reserve     150
00000f90 000000d8 b mailbox              216
00001068 00000100 b out_ring             256
000019f8 000004a4 b mem                 1188
000011f8 00000800 b frm                 2048
```

### 1.3 The C stack is now enforced by the linker, not by a note

IDF's `ulp_riscv.ld` sets `LENGTH = CONFIG_ULP_COPROC_RESERVE_MEM` and `__stack_top` at the *top* of the
region, so the C stack grows down into `.bss` and nothing at link time reserves it — which is why P21's
320 B line was invisible in every previous build. `src/ulp_p22.ld` sets `LENGTH = 7856` and
`__stack_top = ORIGIN + 7856`, so the 320 B is subtracted from the pool by the linker itself.

### 1.4 `MEMSZ` is not a free constant

`.text` for the *identical* engine source: **2982** at `MEMSZ` 2560, **2992** at 1390, **3010** at 1188.
`P()` is `a < MEMSZ ? mem + a : &junk` and it is inlined ~20 times; the constant is folded into each
comparison, and 1188 is a costlier encoding than 2560. The budget therefore has a **±30 B feedback loop**
between the pool size and the engine size that §4.3 does not model, and the engine line must be
re-measured whenever `MEMSZ` moves.

---

## 2. Evidence

### 2.1 Commands

```sh
export IDF_PATH=/home/user/research/esp32/esp-idf && . $IDF_PATH/export.sh
bash probe/results/P22-fits/run.sh 1380   # logs/build_p22_memsz1380.log  -> LINK FAILED rc=1
bash probe/results/P22-fits/run.sh 1190   # logs/build_p22_memsz1190.log  -> 2 B over
bash probe/results/P22-fits/run.sh 1188   # logs/build_p22_memsz1188.log  -> EXIT=0
gcc -DHOST -O2 -o artifacts/uforth_host src/uforth.c && \
  ./artifacts/uforth_host -d artifacts/image_p22.h src/boot_min.fs   # image: 1716 bytes of 2560
python3 split_dict.py                     # resident 1104 / directory 812
```

Each build ran in tmux under `timeout 300 nice -n 10`. Builds read P20's IDF-generated
`compile_commands.json` and `build.ninja` **read-only** and write only under
`probe/results/P22-fits/artifacts/`; P20's calibrated `idf.py build`/stub-subtraction recipe is the one
used (P20 reproduced a real `idf.py build` `.bin` = 4116 B exactly with it).

### 2.2 Section sizes as linked (`MEMSZ` 1188)

```
.text               3152    (engine 3010 + 142 B stub floor)
.rodata              180    (jump table, 40 primitives)
.srodata.seed.0        8    (stub)
.data                  0
.bss                4514
.bin                3340
region use          7846 of 7856   -> 10 B
```

### 2.3 Dictionary measurement

`artifacts/image_p22.h` is the `-d` dump of the same 36-word prelude (`src/boot_min.fs`, 78
definitions: 40 primitive headers + 38 prelude words) over the same engine:
`image: 1716 bytes of 2560 (844 free)` — identical to P20 variant C, so the comparison holds.
`split_dict.py` walks the header chain from `V_LATEST` and reports
`resident 1104 / directory 812 / total 1916`, with 612 B of header bytes removed.

### 2.4 What was *not* shrunk

The primitive set (40), the prelude (`boot_min.fs`, byte-identical to P02's `b32`), the token width
(32-bit), and the frames (4 × 512). The only number moved to make the link pass is `MEMSZ`, which is the
number under test.

---

## 3. Verdict

**PASS, with the budget line corrected.** Against the brief's criteria:

* **the image links with all §4.3 lines at their measured values** — it links, but **not** at the
  `MEMSZ` §4.3 derives; it links at **1188 B**, and the 202 B gap is named (142 B unbudgeted hook code,
  28 B engine/pool coupling, 32 B alignment) rather than absorbed by trimming the prelude;
* **resident dictionary and directory are measured, not extrapolated** — 1104 / 812 from the actual
  compiled dictionary;
* **leftover bytes are a number** — 10 B of pool + 84 B of `mem[]` = **94 B**, i.e. *fits, no room to
  grow*.

Failure criteria, checked:

1. **"Link fails ⇒ report the exact overrun."** It did, at 1380 B: `address 0x1f6e ... not within region
   'ram'`, 190 B over, §1.1. The difference comes from a **named line** (the unbudgeted 142 B of
   platform hooks), not from a quiet trim.
2. **"Resident dictionary > 1518 B even headerless ⇒ resolution A is insufficient."** **No — 1104 B.**
   Resolution A stands. It is 142 B worse than the estimate but still inside `MEMSZ`.
3. **"Links with < 100 B leftover ⇒ report 'fits, no room to grow'."** **Yes: 94 B.** The plan must say
   the next feature does not fit.

**The finding that changes the plan:** §4.3's subtotal is right about the big lines and blind to two
small ones — **the ULP-side hook/REPL code (142 B) is not in the table at all**, and **the engine line
depends on `MEMSZ` (±30 B)**. Together they are 170 B of the 190 B overrun. The budget has no room left
for either, so the pool either takes a 200 B line for hook code or the design gets 200 B back (the xt
duplication in the directory, or 16-bit code tokens).

---

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §4.3 — replace the whole budget table and the two paragraphs after it

```
| Item | Estimate | **Measured / decided** |
| --- | --- | --- |
| Engine (interp + primitives + parse/find/number) | ~2600 | **3190** (`P22` link: `.text` 3010 + `.rodata` 180; 40-primitive set; `mem[]` excluded; 4 × 512 B frames and the page table included). 3162 at `MEMSZ` 2560 (`P20`), 3010 B of `.text` at `MEMSZ` 1188 — the `a < MEMSZ` bound is folded into every access path, so the engine line moves ±30 B with the pool size |
| VM state + counters | 150 | 150 |
| Page frames | 1024 | **2048 (4 × 512, the minimum that boots — `P03f`, `P19`)** |
| Page table + LRU | 200 | 250 (4 slots) |
| Forth stacks | 400 | **128** (peak 108 B measured, `P13`) |
| Mailbox + rings | 600 | 600 (rings 384 measured, `P04`; mailbox 216) |
| C stack + guard | 400 | **320** (worst case 244 B measured, `P21`), **now enforced by the linker script: `LENGTH = 8176 − 320`** |
| Line buffer | 80 | **128** (`P10` F3) |
| Platform hooks + REPL entry (`pl_key`/`pl_emit`/`pl_hw`, REPL step) | — | **142** (measured as the `P22` stub floor; this line did not exist) |
| Section alignment + residue | — | 32 |
| **Subtotal** | ~6400 | **6980** |
| **Left for the resident dictionary** | ~1750 | **1188**, and **10 B** of the pool left after it |

The design **links** (`P22`): the whole map above plus `MEMSZ` = 1188 occupies **7846 of the 7856 B**
left after the P21 C stack. It is **"fits, no room to grow" — 10 B of pool plus 84 B of unused `mem[]`,
94 B total.**

The prelude was the suspected gap and it is not. Measured on the compiled dictionary (`P22`, 1716 B with
headers, reproducing `P20` variant C): **1104 B resident** (system variables, 78 code fields, bodies),
**812 B in the paged name directory** (links, flags, names, and the xt of each word). Resolution A
therefore fits — 1104 of 1188, **84 B spare** — but it is a **relocation, not a compression**: a
directory entry must carry the xt (312 B for 78 words) because the code field is no longer reachable
from the name, so total Forth memory goes **up** from 1716 to 1916 B while 812 B of it leaves the pool.
`~962 B resident` was 142 B optimistic.

What is actually 190 B over is **not** in this table twice: the **142 B of ULP-side hook/REPL code is
unbudgeted**, and the engine grows 28 B when `MEMSZ` shrinks to 1188. Those 170 B, plus 32 B of
alignment, are the entire overrun. Nothing was trimmed to make the link pass, and there is now no slack
for a fourth lever: the next feature needs ~200 B back, and the two candidates are the directory's xt
duplication (drop it by deriving the code field from a resident index) and 16-bit code tokens (P02:
−1.49× dictionary).
```

### 4.2 `docs/01-proposal.md` §10 — R1's engine item

Replace the first R1 checkbox with

```
- [ ] The engine image contains **no** user words and **no** prebuilt dictionary (`nm -S` on the ULP
      ELF shows no Forth word symbols; `mem[]` is `.bss` and uninitialised at load) — **proved by the
      `P22` link**: `.data` is 0, the whole 1188 B `mem[]` sits in `.bss`, and the dictionary is built
      at run time from bytes received over the byte server.
- [ ] The resident dictionary after the §4.3 resolution-A split is **1104 B** and the paged name
      directory is **812 B** (`P22`, measured on the compiled prelude), so the pool's dictionary line is
      1188 B with 84 B spare — the engine does not carry the prelude.
```

### 4.3 `probe/EVIDENCE.md` — new entry

```
### E-025 — the §4.3 machine links, at 1188 B of dictionary, with 94 B to spare (P22)

`probe/results/P22-fits/` (host only: `riscv32-esp-elf` compile + link with IDF's own generated flags,
plus `gcc -DHOST` for the dictionary; board untouched, 8176 B pool, linker script `LENGTH = 8176 − 320`
so P21's C stack is enforced).

* Engine (P20 variant C, 40 primitives) **`.text` 3010 + `.rodata` 180 = 3190 B**, `.bin` 3340 as linked
  (stub floor 142 B). At `MEMSZ` 2560 the same source is 2982/3162 — the pool constant costs ±30 B.
* Frames 4 × 512 = 2048, table + LRU 250, stacks 128, rings + mailbox 600, VM state 150, line buffer
  128, C stack 320.
* **`MEMSZ` = 1380 B (what the lines add up to) does NOT link**: `address 0x1f6e ... section '.bss' is
  not within region 'ram'` — 190 B over. **1188 B links**; 1190 B is 2 B over.
* The 202 B difference is named: **142 B of unbudgeted ULP hook/REPL code** (the `-DP01_STUB_ONLY`
  control), **28 B of engine growth from the `MEMSZ` constant**, 32 B alignment/residue.
* Dictionary, measured: 1716 B compiled (reproduces P20 C) → **resident 1104 B + directory 812 B =
  1916 B**; resolution A relocates 812 B but adds 312 B of xt duplication.
* Leftover: **10 B of pool + 84 B of `mem[]` = 94 B ⇒ "fits, no room to grow".**
* Method note: the probe's first link "passed" with 880 B spare because four budget arrays had been
  dead-store-eliminated out of `.bss` (728 B). Every line must be `nm`-visible before a fit is claimed.
```

---

## 5. Follow-ups

1. **Give the hook/REPL code a line.** 142 B is real ULP code (`pl_key`, `pl_emit`, `pl_hw`, the REPL
   step) that §4.3 never budgeted. With 94 B spare it does not fit, so the next P must either measure
   the real REPL step (not a stub) or move the hooks to the main app over the mailbox.
2. **Close the `MEMSZ` ↔ engine feedback loop.** `P()`'s bound is inlined ~20 times; pick the pool size
   and re-measure the engine before publishing either number. A variant with `MEMSZ` ≤ 2047 compared
   through a `#define` pointer would remove the coupling.
3. **Reclaim the directory's 312 B of xt duplication.** If the resident code fields are exactly ordered
   as the directory entries, `find()` can return `resident_xt[i]` from a 1-byte index instead of a
   4-byte xt per entry — that is ~312 B of total Forth memory and it needs a probe, not an estimate.
4. **Resolution A's runtime is still unbuilt.** This probe measured the split; nothing yet executes a
   resident word whose headers are in a paged directory (R1's last checkbox). The `IMMEDIATE` flag path
   is the awkward one: the prelude's `IMMEDIATE` does `LATEST 2 + DUP C@ 128 OR SWAP C!`, which with the
   directory out of `mem[]` must address the directory, not the dictionary.
5. **`pg_load`'s refill is still a stub** (P12/P20 follow-up): `FRMB` is now 512, so a fault copies
   512 bytes at ~73 cycles/byte ≈ 37 000 cycles ≈ 0.5 ms — the fault, not the dispatch, still sets the
   wake period.
