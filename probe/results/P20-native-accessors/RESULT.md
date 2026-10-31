# P20 — What do native accessors and a trimmed primitive set buy?

| | |
| --- | --- |
| Result | **PASS on the measurement; both levers are smaller than the brief expected, and the one that matters is neither.** Variant A reproduces P12's **3986 B** exactly. Native `lw`/`sw` **grow** the engine by **+116 B** and buy **nothing** on dispatch — the P12 token fetch already bypasses the byte-wise `rd16`/`rd8` chain (it reads the page frame with 4 `lbu` after one `pg_load` probe), so **D7 is a speed-for-space trade on `@`/`!`/parse, not on dispatch**. Trimming 59 → 40 primitives recovers **240 B of dictionary** (1956 → 1716) and **824 B of engine** — the dictionary half clears the 200 B bar, the engine half is the surprise. Dispatch in C is **726 cycles typical (best 658 / worst 994)**, i.e. **> 400** — so the brief's third failure criterion fires and the next question is the dispatch loop, not the accessor. Variant D **does not fit**: 1716 B of resident dictionary against 1368 B of headroom = **348 B short**. |
| Runs on | host only (IDF `ulp_embed_binary` build + `objdump`); board untouched, no serial device opened |
| Target / toolchain | `esp32s3`, `riscv32-esp-elf-gcc 14.2.0 (esp-14.2.0_20241119)`, ESP-IDF v5.4, `CONFIG_ULP_COPROC_RESERVE_MEM=8176` |
| Sources | `uforth.c` = **P12's engine, verbatim** (P02 32-bit + paging); variants B/C/D are edited copies in `variants/` |
| Wall clock | ~8 min (cold IDF build of A 2.5 min overlapped with the source edits; B/C/D compiled + linked from the same generated flags in 25 s) |

## Record — the four variants

| Variant | engine `.text` | engine total | dictionary for the prelude | dispatch cycles |
| --- | --- | --- | --- | --- |
| **A** baseline (P12, byte-wise) | 3734 | **3986** ✅ = P12 | **1956** (measured; = P02) | 1074 (P14, unpaged basis) / **807** (same paged basis as C) |
| **B** native `lw`/`sw` | 3850 (**+116**) | **4102** (+116) | 1956 | **807** — unchanged |
| **C** B + trimmed primitives | 2982 (**−752**) | **3162** (−824) | **1716** (−240) | **726** typical (658 / 994) |
| **D** C + prelude compiled in | 2982 | 3162 code + **2560** of `mem[]` in `.bin` | 1716 (of 2560 allocated) | 726 |

`.bin` as linked (stub subtracted per P01/P12: `bin − 130`): A **4116 → 3986**, B **4232 → 4102**,
C **3292 → 3162**, D **5852** (engine code 3162 + the 2560-byte resident `mem[]` blob). `.rodata`
252 (A/B) → **180** (C/D, jump table one entry shorter ×19). `.data` 0 in A/B/C; D has 2560 because
`image.h` declares `mem[MEMSZ]` with a partly-initialised array, so the whole 2560 pads into `.data`
(the dictionary content is only 1716 of it). `.bss` 3890 → 1330 in D (`mem[]` leaves `.bss`).

---

## 1. Answers

**Q: Does variant A reproduce P12's 3986 B?**
**Yes, exactly**: `artifacts/ulp_main_A.bin` = **4116 B**, `4116 − 130 = 3986`, engine `.text` 3734 +
`.rodata` 252. The comparison is therefore valid. Dictionary cross-check: the host build of the same
`uforth.c` over the P02 32-bit prelude (`b32/boot_min.fs`) reports **1956 bytes used**, which is
P02's independently measured boot layer — the technique is calibrated before it is used on C.

**Q: What do native accessors (`lw`/`sw` for 4-aligned cells) buy?**

| | A | B | delta |
| --- | --- | --- | --- |
| engine `.text` | 3734 | **3850** | **+116 B** |
| engine total | 3986 | **4102** | **+116 B (+2.9 %)** |
| dispatch, typical | 807 | **807** | **0** |
| `@` / `!` body | 517.0 / 517.6 | **64.9 / 93.5** | **8.0× / 5.5×** (P14's prediction, per primitive) |

The engine **grows**: each of `rd32`/`wr32` gains an alignment test plus an inlined native path, and
they are **called**, not inlined, from ~20 sites, so the test is paid in the callee and the function
stops being a thin wrapper. `@`/`!`/`find`/`mkhdr`/the compiler get the measured 5.5–8× on their
cell access, which is where D7's real value is.

**Q: And the dispatch?** **Nothing at all — 0 cycles.** P14 priced `NEXT` as two byte-wise `rd32`
calls (452 each) because it disassembled **P02's unpaged** engine. P12's engine fetches with
`rd32_paged()`, which resolves the page once and then does **four `lbu` on the frame pointer** — it
never enters `rd16`/`rd8`. So the 452-cycle accessor P14 measured is *not on the dispatch path of the
engine that ships*; D7's headline "dispatch 1074 → 218" does not materialise. What is on the dispatch
path is `pg_load()`'s page probe plus one function's prologue/epilogue (**320.8 cycles** per fetch in
A and B, **280.1** in C, where `pg_load` got inlined into `rd32_paged`).

**Q: What does trimming 59 → 40 primitives buy?**

| | A/B | C | delta |
| --- | --- | --- | --- |
| dictionary for the 36-word prelude | 1956 | **1716** | **−240 B (−12.3 %)** |
| engine `.text` | 3734 / 3850 | **2982** | −752 / −868 B |
| engine `.rodata` (jump table) | 252 | 180 | −72 B |
| engine total | 3986 / 4102 | **3162** | −824 / −940 B |

−240 B of dictionary is real but it is **4.5 % of the 5374 B budget**, not a lever on §4.3's 482 B
gap: the gap is in the *prelude's* 1956 B, and the primitive headers are only ~190 B of the 240.

**Q: Do they fit together (variant D)?** **No.** §4.3's headroom for the resident dictionary is
**1368 B** after the 48 B line buffer; the trimmed prelude is **1716 B** ⇒ **−348 B**. And the `.bin`
number is worse than the dictionary number: because `image.h` is `mem[MEMSZ]` (not sized to HERE),
the blob is **2560 B**. D's total footprint would be 3162 + 2560 = 5722 B of engine+image on top of
frames/stacks/rings, i.e. the brief's failure criterion fires.

### 1.1 Dispatch accounting for variant C (recomputed from the listing, not estimated)

Same method as P14's §2.3–2.6 (P05 class weights: `ALU 4.0`, `LW 8.1`, `LB/SB 8.6`, `BR 4.0`), read
from `variants/C/ulp_stubs_C.dis`, on the **page-table hit** path.

| block | listing | cycles |
| --- | --- | --- |
| `NEXT` (`.L141`: `beqz ip`, `mv`, `auipc/jalr rd32_paged`, `mv`, `addi ip,4`, `j .L95`) | 6 insns | 28.0 + fetch |
| dispatch head (`.L95`: `mv`, `auipc/jalr`, `mv cf`, `bltu` bounds, `slli`, `mv`, `add`, `lw` jt, `jr`) | 9 insns | 40.1 + fetch |
| `rd32_paged` (`.text.rd32_paged`, 47 insns — inlined `pg_load` probe + one call to `rd8_paged` for the frame, then 4 `lbu` assembly) | 47 | **280.1** |
| **every dispatch pays** (`NEXT` + head + 2 × fetch) | | **628.3** |
| `+` body (P14 §2.5, unchanged source) | 19 | 97.5 |
| best: `DROP` body | 5 | 29.2 |
| worst: `LIT` body (`rd32_paged(ip)` + `PUSH` + `ip += 4`) | 28 + 280.1 + 57.3 | 365.4 |

| case | C | A (same basis) | P14's unpaged baseline |
| --- | --- | --- | --- |
| best | **657.5** | 738.9 | 1 005.7 |
| **typical** | **725.8** | **807.2** | 1 074.0 |
| worst | **993.7** | 1 115.8 | 1 506.0 |

`NEXT` + head = **628 of 726 = 87 %** of a dispatch, and **2 × 280 = 561 of those 628 (89 %) is the
two token fetches** — of which the four `lbu`s are 34.4 and the page probe + call overhead is 246.
The primitive is 13 %.

### 1.2 The three consequences, re-stated in ticks and µs for variant C

`122.6 cycles/tick`, 1 tick = 6.46 µs.

| | cycles | ticks | µs / ms | vs A (807.2) |
| --- | --- | --- | --- | --- |
| 4-token typing slice (`k = 4`) | 4 × 725.8 = 2 903 | **23.7** | **153 µs** | 170 µs (−10 %) |
| one prelude definition line (`:` + `;`, 2 dispatches) | 1 452 | **11.8** | **76.5 µs** | 85 µs |
| 505-dispatch token (P04 `BIG`) | 505 × 725.8 = 366 529 | **2 990** | **19.3 ms** | 21.5 ms (−10 %) |
| best / worst, 4-token slice | 2 630 / 3 975 | 21.5 / 32.4 | 139 / 209 µs | |
| 22-tick wake (2 697 c) retires | | **3.7 dispatches** | | 3.3 |

**One page miss dwarfs all of this**: the refill loop in `pg_load` copies 256 bytes through `rd8`
(≈ 73 cycles per byte) ⇒ **≈ 18 700 cycles ≈ 153 ticks ≈ 0.99 ms per fault**, i.e. **26× the whole
dispatch cost**. At 4 frames a hot-set miss is the dominant term, not the interpreter.

---

## 2. Evidence

### 2.1 Commands

```sh
export IDF_PATH=/home/user/research/esp32/esp-idf && . $IDF_PATH/export.sh
bash probe/results/P20-native-accessors/build.sh        # A: set-target + idf.py build, logs/build_A.log, EXIT=0
bash probe/results/P20-native-accessors/run_variants.sh # B/C/D: same flags, logs/variants.log, EXIT=0
```

Both ran in tmux under `timeout 300 nice -n 10`. A is the **real IDF build** (1050 steps, zero
warnings/errors, `EXIT=0`); B/C/D are compiled from the `compile_commands.json` IDF itself generated and
linked with the same `LINK_FLAGS` from `build.ninja` minus the engine object — P01/P12's recipe, one
`-D` apart (`-DP01_STUB_ONLY` control = 84 B, `-DIMAGE` for D).

### 2.2 Sizes and the stub subtraction

```
control: bin=84  text=84  rodata=0 srodata=0 data=0 bss=4     # 84 + pl_emit 38 + seed 8 = 130
B: bin=4232 text=3972 rodata=252 srodata=8 data=0    bss=3890
C: bin=3292 text=3104 rodata=180 srodata=8 data=0    bss=3890
D: bin=5852 text=3104 rodata=180 srodata=8 data=2560 bss=1330
A (idf.py build): artifacts/ulp_main_A.bin = 4116; .text 3856 .rodata 252 .srodata.seed.0 8
```

engine `.text` = `.text − 122` (startup 76 + `main` 8 = 84, plus `pl_emit` 38), engine total =
`.bin − 130`. A: 3856 − 122 = 3734, 4116 − 130 = **3986** ✅.

### 2.3 Dictionary, measured on the host, same prelude, same engine

`gcc -DHOST` build of each variant's `uforth.c`, `-d` dump after interpreting
`probe/results/P02-token-width/b32/boot_min.fs` (the 36-word 32-bit prelude):

```
A: image: 1956 bytes of 2560  -> variants/image_A32.h      (= P02's measured boot layer)
C: image: 1716 bytes of 2560  -> variants/D/image.h        (-240 B)
```

D's `mem[]` blob is 2560 in `.bin` because `image.h` sizes the array `MEMSZ`, not HERE — a 844-byte
zero tail is paid for in flash-to-RTC copy. A tightly sized `image.h` would cost 1716.

### 2.4 The dispatch loop in C (quoted, `variants/C/ulp_stubs_C.dis`)

```asm
; .L95 — dispatch head: cf = rd32_paged(w), bounds, jump table, jr
  d2: mv   a0,s0        ; ALU
  d4: auipc ra,0x0      ; ALU   R_RISCV_CALL_PLT rd32_paged
  d8: jalr ra           ; ALU
  dc: mv   s10,a0       ; ALU   cf
  de: bltu s8,a0,fe     ; BR    cf > 44 -> .L141 (return path)
  e2: slli a5,a0,0x2    ; ALU
  e6: mv   a4,s9        ; ALU   jump-table base
  ea: add  a5,a5,a4     ; ALU
  ec: lw   a5,0(a5)     ; LW    jump table entry
  ee: jr   a5           ; ALU   -> handler
; .L141 — NEXT: if (!ip) return; w = rd32_paged(ip); ip += 4;
  fe: beqz s1,52        ; BR
 100: mv   a0,s1        ; ALU
 102: auipc ra,0x0     ; ALU   R_RISCV_CALL_PLT rd32_paged
 106: jalr ra          ; ALU
 10a: mv   s0,a0       ; ALU   w
 10c: addi s1,s1,4     ; ALU   ip += 4
 10e: j    d2          ; ALU
```

head = 7 ALU + 1 BR + 1 LW = 40.1; NEXT = 6 ALU + 1 BR = 28.0. Both add `rd32_paged`.

`.text.rd32_paged` (C, 47 instructions) is the whole page-hit fetch: 17-instruction prologue (8 `sw`),
the 4-entry probe `lw`/`beq`, the 4-`lbu` assembly, and 8 `lw` + `addi`/`ret` epilogue — **16 ALU +
4 LB + 8 LW in the assembly tail alone**. Compare A/B: the identical function is **29** instructions
plus an out-of-line `pg_load` (17 + 2 + 9) because `pg_load` did not inline; A/B fetch = 320.8, C =
280.1. The 40-cycle difference is an **inlining side effect of the smaller engine**, not a property of
the trim — noted so nobody credits the accessor with it.

### 2.5 What the trim actually removed (variant C, `variants/C/uforth.c`)

`PRIMS` 59 → 40 entries, and the matching `case P_*` blocks (the switch and the table are trimmed
together — a table entry with no case falls into the colon-word default and executes garbage).
Dropped: `W@`, `W!`, `U/MOD`, `KEY?`, `MS`, `."`, `(.")`, `(`, `LITERAL`, `C,`, `W,`, `J`, `UNLOOP`,
`U<`, `XOR`, `INVERT`, `LSHIFT`, `RSHIFT`, `WAKE`.
**Two deviations from the brief's list, both forced and both recorded**: `ROT` is **kept** (the 32-bit
prelude's `*/` is `SWAP ROT * SWAP /`, so dropping it makes variant D unbuildable) and `NIP`/`TUCK`
**do not exist as primitives** in this engine (they are prelude words). `\` is kept (the prelude is
full of comments). Keeping `ROT` costs 5–6 B of `.text` and ~32 B of header; the 240 B figure is
therefore a floor-clearance result, not an optimum.

---

## 3. Verdict

**PASS.** Four variants measured with P12's recipe and its stub subtraction; A reproduces 3986 B, so
the comparison is valid; dispatch for C is recomputed from the listing (§2.4, §1.1), not estimated.

Against the brief's failure criteria:

1. **"Native accessors grow the engine ⇒ state the cost."** **TRUE — +116 B of `.text`, +2.9 %.** D7
   is a speed-for-space trade: 8× on `@`, 5.5× on `!` and the same on every `find`/`mkhdr` header walk
   (parse and compile, which P14 did not weigh), **0 % on dispatch**.
2. **"Trimming recovers < 200 B ⇒ not the lever it looked like."** **FALSE — 240 B of dictionary**
   (1956 → 1716) plus **824 B of engine**. The dictionary gain clears the bar but is only 4.5 % of the
   §4.3 gap; the engine gain is the larger and unexpected half (19 primitives × ~28 B of `.text` and
   72 B of jump table).
3. **"Dispatch still > 400 cycles in C ⇒ `NEXT`'s two-fetch design is the problem."** **TRUE, by
   1.8× — 726 typical.** And the brief's named fix is confirmed by the listing: the fetches are 561
   of 628 cycles and the *page probe inside* `rd32_paged` is 246 of that, so **caching the resolved
   frame pointer per token class** (or per page, with a compare) is worth ~2× on dispatch. That is the
   next question, and it is now the first-ranked one.
4. **"Variant D does not fit ⇒ report the overrun."** **TRUE — 1716 B against 1368 B of headroom =
   348 B short** (and 2560 B in `.bin` as `image.h` is written). The resident-prelude resolution does
   not survive the trimmed set either; it needs another 348 B of dictionary or another 348 B of pool.

**The finding that reorders the plan:** P14's most-quoted number — `rd32` = 452 cycles, "84 % of a
dispatch" — describes the **accessor in P02's unpaged engine**, not the fetch path of the engine that
ships. In the paged engine the token fetch is a page probe + 4 `lbu` (280–321 cycles), which is *why*
D7 moves the dispatch by zero. `NEXT` is still 87 % of a dispatch, but what it pays for is
**paging**, not the byte-wise accessor. §4.3/§5/§8 and D7 must all say that instead.

---

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §4.3 — engine and dictionary lines from variant C/D

Replace the engine row

```
| Engine (interpreter, primitives, parse/find/number) | 3986 (measured, P12: `.text` 3734 + `.rodata` 252, `mem[]` excluded, 4 × 256 B frames and the page table included) |
```

with

```
| Engine (interpreter, primitives, parse/find/number) | 3162 (measured, P20 variant C: `.text` 2982 + `.rodata` 180, 40-primitive set, `mem[]` excluded, 4 × 256 B frames and the page table included). The 59-primitive P12 build is 3986; native `lw`/`sw` accessors alone cost +116 B, the trim −940 B. |
```

and replace the closing spare paragraph (the text P12 handed back) with

```
The resident dictionary at 32-bit and with the trimmed 40-primitive set is **1716 B** (P20, host
measurement of the same 36-word prelude that gives 1956 B untrimmed). Against 1368 B of headroom after
the 48 B line buffer, the spare is **−348 B**: the prelude still does not fit resident, and a compiled-in
`image.h` costs **2560 B** of `.bin` because the array is sized `MEMSZ`, not HERE. Trimming the
primitive set is worth 240 B of dictionary and 824 B of engine — real, but 4.5 % of the gap.
```

### 4.2 `docs/01-proposal.md` §5 and §8 — dispatch cycles and the connected period

Replace P14's per-dispatch paragraph (the text P14 handed back in §4.1) with

```
**Per-dispatch arithmetic** (P20, same P05 weights, applied to the listing of the engine as built —
P12's paged 32-bit engine): one primitive dispatch costs **628 cycles before the primitive runs** —
`NEXT` 308 + dispatch head 320 — and **658 / 726 / 994 cycles** best / typical / worst including the
handler. 87 % of a dispatch is `NEXT` + head, but it is no longer the byte-wise accessor that they pay
for: the token fetch is `rd32_paged()` — one `pg_load()` page probe plus four `lbu` on the frame — at
**280 cycles**, so the two fetches are 561 of 628 and the page probe alone is 246. Native `lw`/`sw`
accessors (D7) change this by **zero cycles** and cost **+116 B** of engine; what they fix is `@`/`!`
and the parse/compile header walks (8.0× and 5.5× per primitive). A 22-tick wake (2 697 cycles)
retires **3.7 dispatches**; a 4-token typing step is **23.7 ticks (153 µs)**; one prelude line is
**11.8 ticks (76.5 µs)**; P04's 505-dispatch token is **2 990 ticks (19.3 ms) = 136× the floor and
643× the 30 µs connected budget**. One page miss is **≈ 18 700 cycles (0.99 ms) — 26 dispatches**, and
dwarfs the dispatch cost, so the hot-set fault rate is the real period driver.
```

### 4.3 `docs/03-prototype-review.md` D7 — resolved: measured effect on both size and speed

Replace the D7 paragraph P14 handed back with

```
Measured, not estimated (P20). P05 is right that a byte load costs 8.6 cycles against 8.1 for a native
`lw`, and P14 is right that the byte-wise `rd32` costs **452 cycles** — but that accessor is only on
the *data* path. The engine as built fetches tokens through `rd32_paged()`, which resolves the page once
and then does four `lbu` on the frame (280 cycles including the page probe); it never enters
`rd16`/`rd8`. So D7, measured on four builds of the same engine: **`@`/`!` and the parse/compile header
walks get 8.0×/5.5×**, and the **dispatch gets nothing at all (807 → 807 cycles)** while the engine
**grows +116 B** (`.text` 3734 → 3850) because each accessor gains an alignment test and an inlined
native path. **D7 is resolved as: adopt it for the data path and for `find`/`mkhdr`, and do not expect
it to fix dispatch; budget +125 B of engine for it.** The dispatch target is the two token fetches and
the page probe inside them (561 of 628 cycles) — caching the resolved frame pointer per token class is
worth ~2×, and that, not threading, is the next item.
```

### 4.4 `probe/EVIDENCE.md` — extend E-021/E-023

```
### E-021 (P20 addition) — native accessors and a trimmed primitive set, four builds (P20)

`probe/results/P20-native-accessors/` (host only; P12's engine verbatim + edited copies; P01/P12's
IDF recipe, `-DP01_STUB_ONLY` control = 130 B stub floor).

* A (P12 baseline) reproduces **3986 B** (`.bin` 4116 − 130, `.text` 3734 + `.rodata` 252) — the
  comparison is valid, and the host dictionary measurement reproduces P02's **1956 B**.
* B (native `lw`/`sw` on 4-aligned cells): engine **4102 B (+116)**, `.text` 3850. Dispatch
  **unchanged (807)**; `@`/`!` bodies 64.9/93.5 vs 517.0/517.6.
* C (B + 59 → 40 primitives): engine **3162 B (−824)**, `.text` 2982, `.rodata` 180; dictionary for
  the 36-word prelude **1716 B (−240)**.
* D (C + prelude compiled in): engine code 3162 + **2560 B** resident `mem[]` in `.bin` (1716 used) ⇒
  **348 B over** §4.3's 1368 B headroom.
* Dispatch, C, from the listing: **658 / 726 / 994** best/typical/worst; `NEXT`+head 628 of which the
  two `rd32_paged` fetches are 561 and the page probe 246. A page miss ≈ **18 700 cycles (0.99 ms)**.

### E-023 (P20 addition) — D7 is not a dispatch optimisation

P14 derived "dispatch 1074 → 218 with D7" by re-weighting P02's unpaged listing. P20 compiled the D7
accessors into the paged engine and re-weighted the actual output: dispatch **807 → 807**, engine
**+116 B**. The fetch path (`rd32_paged`) never used the byte-wise accessor chain, so P14's §1.2 table
is a property of the unpaged engine only. What D7 buys is `@`/`!`/`find`/`mkhdr` at 5.5–8× — the
parse-and-compile path, not the dispatch loop.
```

---

## 5. Follow-ups

1. **Cache the resolved frame pointer in the dispatch loop.** 561 of 628 "common" cycles are two
   `rd32_paged` calls whose page probe is 246; a per-token-class cached `u8 *` (or `w`/`cf` both from
   the same page) should take dispatch from 726 to ~350–400. This is the highest-value change left and
   it is a *dispatch-loop* change, not an accessor one.
2. **Re-measure the `@`/`!`/parse win as a whole-token cost.** P20 proves the per-primitive factor; the
   token cost including `word()`/`find()` (P14 §3.3, still unaccounted) is where D7's 8× actually lands,
   and §8 quotes per-token numbers.
3. **`pg_load` is still a stub with a fixed victim and no write-back** (P12 follow-up 3) and its refill
   loop is ~18 700 cycles. Any LRU/dirty-tracking version must be measured against the 726-cycle
   dispatch, not against the 0.99 ms fault, and the fault rate — not the dispatch — is what sets the
   wake period.
4. **The dictionary is still 348 B short of resident.** Two candidate levers, both cheaper than another
   engine trim: name-length elision in primitive headers (240 B came from 19 headers, ≈ 12.6 B each) and
   sizing `image.h` to HERE (D pays 844 B for `MEMSZ` padding).
5. **`ROT` in the prelude vs `ROT` in the trim** — the brief's trim list and the 36-word prelude
   disagree; the prelude won here. If the prelude is revised (`*/` without `ROT`), C loses another
   ~32 B of header and ~6 B of `.text`.
