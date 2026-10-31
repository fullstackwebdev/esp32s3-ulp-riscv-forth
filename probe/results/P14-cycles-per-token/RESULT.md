# P14 — What does one token cost in cycles?

**Status: PASS (host-only static accounting, one run).** Every path below is an actual instruction listing
from `riscv32-esp-elf-objdump -d` of the P02 32-bit `uforth.c` compiled for the ULP core, weighted with P05's
measured class costs. Headline: **one primitive dispatch costs ≈ 1 000–1 500 cycles, ~90 % of which is `NEXT`**
— because the 32-bit token fetch goes through the byte-wise accessor `rd32` (`452 cycles` per 32-bit read), and
`NEXT` does **two** of them per dispatch (token → xt, xt → code field). A 22-tick wake (2 697 cycles) therefore
retires **2–3 dispatches**, not 4 tokens; a 4-token typing slice needs **≥ 35 ticks (226 µs)**, and P04's
505-dispatch token needs **4 424 ticks (28.6 ms)** — 953× the 30 µs connected budget. All four failure criteria
in the brief fire.

Project: `probe/results/P14-cycles-per-token/` (`uforth.c` copied verbatim from
`probe/results/P02-token-width/b32/`, `uforth.o`, `uforth.dis`, `uforth-dr.dis`).
Nothing was measured on the board; nothing outside this directory was written.

---

## 1. Answers

| Path | instructions | weighted cycles |
| --- | --- | --- |
| `rd8` / `wr8` (the leaf accessor) | 8 | **36.6** |
| `rd16` / `wr16` | 20 / 17 (+2/4 calls) | 177.8 / 165.8 |
| `rd32` / `wr32` | 18 (+2 calls each to `rd16`) | **452.2** / 428.2 |
| `PUSH` / `RPUSH` | 11 | 57.3 |
| **`NEXT`** (`.L155`: `if(!ip) return; w = rd32(ip); ip += 4;`) | 7 + call to `rd32` | **480.2** |
| **dispatch head** (`.L89`: `cf = rd32(w)` + bounds + jump table + `jr`) | 10 + call to `rd32` | **496.3** |
| **`NEXT` + head = what every dispatch pays** | 17 + 2 calls to `rd32` | **976.5** |
| `DUP` (body only) | 14 + `PUSH` | 122.0 |
| `@` (body only) byte-wise / native `lw` | 13 + `rd32` / 11 | **517.0 / 64.9** (8.0×) |
| `!` (body only) byte-wise / native `sw` | 19 + `wr32` / 19 | 517.6 / 93.5 (5.5×) |
| `P_DOCOL` / `P_EXIT` (body only) | 4 + `RPUSH` / 13 | 69.3 / 65.3 |
| `0BRANCH` body, flag ≠ 0 (fall through, `ip += 4`) | 14 | 69.3 |
| `0BRANCH` body, flag = 0 (take branch: `ip = rd32(ip)`) | 19 + `rd32` | 533.5 |
| `LIT` body (`PUSH(rd32(ip)); ip += 4`) | 7 + `rd32` + `PUSH` | 537.5 |
| `+` body | 19 | 97.5 |
| **cycles per dispatch (best / typical / worst)** | | **1 006 / 1 074 / 1 506** |
| **cycles per token** | 1 dispatch, unless the token is a colon word | **≈ 1 006 / 1 074 / 1 506**; a colon-word token = 1 `DOCOL` + all its body dispatches + 1 `EXIT` |
| 4-token slice (`k = 4`) → ticks / µs | 4 × 1 074 = 4 296 | **35.0 ticks / 226 µs** (best 32.8 / 212, worst 49.1 / 317) |
| one prelude definition line (2 dispatches: `:` + `;`) → ticks / µs | 2 × 1 074 = 2 148 | **17.5 ticks / 113 µs** (parse not counted — see §3.4) |
| 505-dispatch token (P04 `BIG`) → ticks / ms | 505 × 1 074 = 542 370 | **4 424 ticks / 28.6 ms** (best 4 144 / 26.8, worst 6 203 / 40.1) |

Composition of a dispatch (typical, `+`):

```
NEXT           480.2  (49.3 %)
dispatch head  496.3  (50.9 %)   of which 452.2 is rd32(w)
handler +       97.5  ( 9.1 %)   <- the actual Forth work
               -----
               1074.0
```

**`NEXT` + head = 976.5 of 1 074 = 90.9 % of a dispatch. The primitive is 9 %.** Two thirds of the whole
dispatch is 2 × `rd32`, i.e. **8 byte loads made of 8 `rd8` calls with bounds checks between them**, which is
D7 — not the primitives, and not token threading.

Why 976.5 and not "2 loads": the accounting is per instruction at the measured class costs, so the *bookkeeping*
of the accessor is charged too — `rd32` is 18 instructions of its own plus two calls to `rd16`, each of which is
20 instructions plus two calls to `rd8`, each of which is 8 instructions (bounds check, address build, `lbu`,
`ret`). 4 × 8 leaves = 32 instructions to read 4 bytes; the 4 `lbu`s themselves are only 34.4 of the 452.2 cycles.

### 1.1 The three consequences, as asked

| | cycles | ticks | µs / ms | fits in a 22-tick (2 697 c) wake? |
| --- | --- | --- | --- | --- |
| 4 tokens of typing (a `k = 4` slice) | 4 296 | **35.0** | **226 µs** | **no** — needs 35 ticks, 1.6× the floor |
| one prelude definition line (`: … ;`) | 2 148 | **17.5** | **113 µs** | yes, at 80 % of the floor |
| P04's 505-dispatch token (`BIG`, 100-iteration loop) | 542 370 | **4 424** | **28.6 ms** | **no** — 201× the floor, 953× the 30 µs connected period |

Minimum wake period derived from the measurement:

* **(a) interactive echo, 4 tokens/step, W = 4 steps/wake:** the work per wake is
  `W·k·1 074 = 17 184 cycles = 140 ticks = 905 µs`. One step (4 tokens) is 35 ticks, so with W = 1 the
  minimum period is **35 ticks (226 µs)**; at `k = 4`, W = 4, 140 ticks (905 µs). Both are far above the
  22-tick floor, so **the period is set by the work, not by `ulp_set_wakeup_period`** — the floor stops
  mattering for typing.
* **(b) compiling one line from the prelude:** 2 dispatches (`:` and `;`; every token between them is compiled
  by `cw()`, which is not a dispatch) ⇒ **17.5 ticks (113 µs)**, so a 22-tick wake compiles one line per wake.
  Note the real cost of a compile line is `word()` + `find()`, which is not in this accounting (§3.4).
* **(c) running a 100-iteration loop:** that is P04's 505-dispatch token ⇒ **4 424 ticks (28.6 ms)**. At the
  connected period of 32–64 ticks this token needs **69–138 wakes**, so it must be *resumable at a dispatch
  boundary* — the token budget cannot bound it (P04's Delta 1, now with numbers).

### 1.2 What it would cost with D7 done

Replacing `rd32` with a native `lw` (and `wr32` with `sw`) removes 3 call layers and 8 bounds-checked byte
accesses per cell:

| | today | D7 (native `lw`/`sw`) | factor |
| --- | --- | --- | --- |
| `rd32` (one 32-bit read) | 452.2 | 24.1 (call + `lw` + `ret`) | 18.8× |
| dispatch, typical (`+`) | 1 074 | **218** | 4.9× |
| `@` / `!` body | 517.0 / 517.6 | 64.9 / 93.5 | 8.0× / 5.5× |
| 4-token slice | 35.0 ticks | **7.1 ticks** | 4.9× |
| 505-dispatch token | 4 424 ticks (28.6 ms) | **898 ticks (5.8 ms)** | 4.9× |

With D7 the dispatch falls to **≈ 218 cycles**, of which `NEXT`+head is still **120.3 (55 %)** — so the
dispatch loop stays the dominant term and is the *next* target after the accessor (inlining `rd32`, keeping a
cached `cf`, or token threading). Inlining the byte-wise accessor alone (leaving it byte-wise, but as
`static inline`) would give `rd32 ≈ 146` (32 leaf instructions + 4 `lbu`) and a dispatch of ≈ 486 (2.2×) for a
one-line change. Both are recorded as follow-ups, not decisions.

---

## 2. Evidence

### 2.1 Build and disassembly (the only two commands that produced numbers)

```sh
cp probe/results/P02-token-width/b32/uforth.c probe/results/P14-cycles-per-token/uforth.c
export IDF_PATH=/home/user/research/esp32/esp-idf && . $IDF_PATH/export.sh
timeout 30 riscv32-esp-elf-gcc -Os -march=rv32imc_zicsr_zifencei -mdiv \
      -ffunction-sections -fdata-sections -c uforth.c -o uforth.o     # text 4839, bss 2782
timeout 30 riscv32-esp-elf-objdump -d  uforth.o > uforth.dis
timeout 30 riscv32-esp-elf-objdump -dr uforth.o > uforth-dr.dis      # with relocation names
```

No `-DIMAGE`: `mem[]` is the plain `static u8 mem[MEMSZ]` array, which is how the RAM-only ULP build looks; it
changes only the address encoding (`lui`+`addi` for `mem`), not the instruction count. `-Os` inlined `run()` and
`interpret()` into one out-of-line function (`forth_quit` in the listing — the symbol is the host REPL entry
that `run()` got inlined into), which is why there is no `<run>` symbol; the dispatch loop is therefore visible
exactly once, at `.L89`/`.L155`.

**Relaxation caveat.** The dump is a relocatable object without `-mrelax`; every `auipc x,0x0` + `mv x,x` /
`lui x,0x0` + `mv x,x` pair carries `R_RISCV_RELAX` and becomes a 2-instruction `lui`+`addi` (or a gp-relative
`addi`) after linking — **the instruction count does not change**, so the weighting is unaffected. The `jalr`
targets are unresolved in `-d`; they are resolved by name in `uforth-dr.dis` and every call was read from
there, not guessed (e.g. `.L155+0x4 → R_RISCV_CALL_PLT rd32`).

### 2.2 The class weights (P05, measured, not re-derived)

`ALU = 4.0` (dependent `addi`), `LW = LR = 8.1` (RTC-RAM word load), `LB = SB = 8.6` (byte load, and stores
"the same as loads" per the brief), `BR = 4.0`. Tick `122.6` cycles, 1 tick `= 6.46 µs`, core `19.0 MHz`.

Why summing per instruction is the right model here: P05 measured 4.0 cycles for *dependent* `addi` in a tight
loop, i.e. the **retire interval per instruction**, not just ALU latency — the core fetches instructions from
RTC memory, so the 4 cycles already include the fetch. Summing instruction slots is therefore a first-order
model with no overlap credit; it is the conservative (high) end, and the conclusions in §1 survive a ±30 % error
in any single weight.

### 2.3 The dispatch loop (quoted)

```asm
; .L89 — dispatch head: cf = rd32(w), bounds check, jump table, jr
 12e: mv   a0,s1                       ; ALU
 130: auipc ra,0x0                     ; ALU   R_RISCV_CALL_PLT rd32
 134: jalr ra                          ; ALU
 138: mv   s10,a0                      ; ALU   cf
 13a: bltu s8,a0,17c <.L155>           ; BR    cf > 63 -> fault path
 13e: slli a5,a0,0x2                   ; ALU
 142: mv   a4,s9                       ; ALU   jump-table base (.rodata)
 146: add  a5,a5,a4                    ; ALU
 148: lw   a5,0(a5)                    ; LW    jump table entry
 14a: jr   a5                          ; ALU   -> handler
; .L155 — NEXT: if (!ip) return; w = rd32(ip); ip += 4;
 17c: beqz s0,b2 <.L85>                ; BR    if (!ip) return
 17e: mv   a0,s0                       ; ALU
 180: auipc ra,0x0                     ; ALU   R_RISCV_CALL_PLT rd32
 184: jalr ra                          ; ALU
 188: mv   s1,a0                       ; ALU   w = rd32(ip)
 18a: addi s0,s0,4                     ; ALU   ip += 4
 18c: j    12e <.L89>                  ; ALU
```

head = 8 ALU + 1 BR + 1 LW = 32 + 4 + 8.1 = 44.1, plus `rd32` = **496.3**
NEXT = 6 ALU + 1 BR = 24 + 4 = 28, plus `rd32` = **480.2**
**Common = 976.5 cycles, paid by every dispatch.**

### 2.4 The byte-wise accessor chain (quoted)

`.text.rd8` — the leaf, 8 instructions, **36.6 cycles**:

```asm
   0: lui   a5,0x1                     ; ALU   a5 = 0x1000
   2: addi  a5,a5,-1537               ; ALU   a5 = 2559 = MEMSZ-1
   6: bltu  a5,a0,1a <.L3>            ; BR    a < MEMSZ ? (not taken on the fast path)
   a: lui   a5,0x0                     ; ALU   R_RISCV_HI20 mem
   e: mv    a5,a5                      ; ALU   R_RISCV_LO12_I mem (relaxed: addi)
  12: add   a0,a0,a5                    ; ALU   mem + a
  14: lbu   a0,0(a0)                   ; LB    8.6
  18: ret                             ; ALU
```

`.text.rd32` — 18 instructions, 12 ALU + 3 SW + 3 LW, plus two calls to `rd16` = **452.2 cycles**:

```asm
   0: addi  sp,sp,-16     ; ALU      22: lw   ra,12(sp)   ; LW
   2: sw    ra,12(sp)     ; SW       24: or   a0,a0,s0    ; ALU
   4: sw    s0,8(sp)      ; SW       26: lw   s0,8(sp)    ; LW
   6: sw    s1,4(sp)      ; SW       28: lw   s1,4(sp)    ; LW
   8: mv    s1,a0         ; ALU      2a: addi sp,sp,16    ; ALU
   a: auipc ra,0x0        ; ALU      2c: ret             ; ALU
   e: jalr  ra            ; ALU  -> rd16(a)
  12: mv    s0,a0         ; ALU
  14: addi  a0,s1,2      ; ALU
  18: auipc ra,0x0       ; ALU
  1c: jalr  ra            ; ALU  -> rd16(a+2)
  20: slli  a0,a0,0x10   ; ALU
```

`.text.rd16` — 20 instructions, 14 ALU + 3 SW + 3 LW, plus two calls to `rd8` = **177.8 cycles**; `wr16` is the
same shape (17 instructions, 11 ALU + 3 SW + 3 LW, + two `wr8`) = **165.8**; `wr32` = 18 instructions, 12 ALU +
3 SW + 3 LW, + two `wr16` = **428.2**; `wr8` = `rd8` with `sb` = **36.6**.

So a 32-bit read is `2 × (2 × 36.6 + 92.6/2 ...)` — spelled out: `452.2 = 48 (12 ALU) + 24.3 (3 SW) + 24.3 (3 LW)
+ 2 × 177.8`, and `177.8 = 56 (14 ALU) + 24.3 + 24.3 + 2 × 36.6`, and `36.6 = 28 (7 ALU) + 8.6 (1 LB)`.
**The four `lbu`s are 34.4 cycles of 452.2 (7.6 %). The other 92 % is bounds checks, address arithmetic,
prologue/epilogue and three levels of call.** That is the single most important number in this probe.

### 2.5 Stack helpers and the primitives, quoted

`PUSH`/`RPUSH` (identical code, 11 instructions): `lui`, `lbu sp`, `lui`+`mv ds`, `andi sp,15`, `slli 2`, `add`,
`addi sp,1`, `sw v,0(p)`, `sb sp`, `ret` = 8 ALU (32) + LB 8.6 + SW 8.1 + SB 8.6 = **57.3**.

`DUP` (`.L140` → `.L265` → `.L259` → `.L248`, 14 instructions + `PUSH`) = **122.0**:

```asm
 328: lui a5,0x0        ; ALU    33e: j   2de <.L259>   ; ALU
 32c: lbu a5,0(a5)      ; LB   (sp)
 330: lui a4,0x0        ; ALU    2de: add a5,a5,a4    ; ALU
 334: addi a5,a5,-1     ; ALU    2e0: lw  a0,0(a5)     ; LW   TOS
 336: andi a5,a5,15     ; ALU    2e2: j   194 <.L248>  ; ALU
 338: slli a5,a5,2      ; ALU    194: auipc ra,0x0     ; ALU  -> PUSH
 33a: mv   a4,a4        ; ALU    198: jalr ra           ; ALU
                                19c: j   17c <.L155>   ; ALU  -> NEXT
```

`@` (`.L133` → `.L261`, 13 instructions + `rd32`) = **517.0** — the only difference from a native `lw` is the
pair `auipc/jalr` at `41c/420`:

```asm
 402: lui  a5,0x0       ; ALU    41a: lw  a0,0(s1)    ; LW   TOS
 406: lbu  a5,0(a5)     ; LB  (sp)
 40a: lui  s1,0x0       ; ALU    41c: auipc ra,0x0    ; ALU  -> rd32(TOS)   <-- D7: becomes lw
 40e: mv   s1,s1        ; ALU    420: jalr ra          ; ALU
 412: addi a5,a5,-1     ; ALU    424: sw  a0,0(s1)    ; SW   TOS =
 414: andi a5,a5,15     ; ALU    426: j   17c <.L155> ; ALU
 416: slli a5,a5,2      ; ALU
 418: add  s1,s1,a5     ; ALU
```

`@` with a native accessor (derived by the same weighting on the same listing with `c088 sw` kept and the
`auipc/jalr`+`rd32` replaced by one `lw`) = 8 ALU (32) + LB 8.6 + LW 8.1 (TOS) + LW 8.1 (the value) + SW 8.1 =
**64.9**. Ratio **8.0×** — D7's 8.5× estimate, confirmed and now *per primitive* as well as per cell.

`!` (`.L132` → `.L260`) = 89.4 (14 ALU + LB + SB + 2 LW) + `wr32` 428.2 = **517.6**; native = **93.5**.

`P_DOCOL` (`.L153`, 4 instructions) = `mv a0,s0` + call `RPUSH` + `addi s0,s1,4` (ip = w+4) = 12 + 57.3 =
**69.3**. It falls straight into `NEXT`.

`P_EXIT` (`.L150`, 13 instructions) = **65.3**:
`beqz s0` (return to C) + `lui/lbu rsp` + `addi/zext` + `sb` (rsp--) + `lui/andi/slli/mv/add/lw` (ip = RPOP()) +
`j .L155` → 9 ALU (36) + BR 4 + LB 8.6 + SB 8.6 + LW 8.1.

`0BRANCH` (`.L147`), **not taken** (flag ≠ 0 ⇒ `ip += 4`, `.L253`) = 14 instructions → 10 ALU (40) + BR 4 +
LB 8.6 + SB 8.6 + LW 8.1 = **69.3**; **taken** (flag = 0 ⇒ `.L256`: `ip = rd32(ip)`) = 61.3 + (4 ALU 16 + `rd32`
452.2 + `j` 4) = **533.5**.

`LIT` (`.L149`) = `rd32(ip)` + `PUSH` + `ip += 4` = 7 ALU (28) + 452.2 + 57.3 = **537.5**. Every literal in a
line is a 1 500-cycle dispatch.

### 2.6 Cycles per dispatch, and the best / typical / worst choice

| case | basis | cycles |
| --- | --- | --- |
| **best** | common 976.5 + `DROP` (`.L139`, 5 insns: 3 ALU + LB + SB = 29.2) | **1 005.7** |
| **typical** | common + `+` (97.5) and `DUP` (122.0) and `0BRANCH`-not-taken (69.3), `EXIT` (65.3) bracket 1 042–1 107; the `+` case is quoted | **1 074.0** |
| **worst** | common + `LIT` (537.5, i.e. any literal) / `@` (517.0) / `!` (517.6) / `0BRANCH`-taken (533.5) | **1 506–1 510** |

Cycles per token = cycles per dispatch, because the interpreter's unit is a dispatch: a primitive token is
exactly one dispatch, a literal is one `LIT` dispatch, and a colon-word token is 1 `DOCOL` + its whole body +
1 `EXIT` (P04: up to 505 dispatches for `BIG`). `find()`/`word()` are *not* dispatched and are not in these
numbers — see §3.4.

### 2.7 Arithmetic for §1.1, shown

```
4 tokens      = 4   × 1 074 = 4 296 c; 4 296 / 122.6 = 35.0 ticks; 35.0 × 6.46 µs = 226 µs
prelude line  = 2   × 1 074 = 2 148 c; 2 148 / 122.6 = 17.5 ticks;             = 113 µs
505 dispatches= 505 × 1 074 = 542 370 c; / 122.6 = 4 424 ticks;                = 28.58 ms
22-tick wake  = 22  × 122.6 = 2 697 c; 2 697 / 1 074 = 2.5 dispatches (2.7 at best case)
30 µs connected budget = 30 / 6.46 = 4.6 ticks = 570 c = 0.53 of one dispatch
```

---

## 3. Verdict

**PASS.** Every path in the Record table has an instruction listing from the disassembler (§2.3–2.5, files
`uforth.dis`, `uforth-dr.dis`), the weighting uses P05's measured class costs with the arithmetic shown (§2.7),
and the three consequences are in ticks and µs (§1.1). No path had to be declared unmeasurable.

Against the brief's failure criteria:

1. **Cycles per dispatch > 200 — TRUE, by 5.4×** (1 074 typical). Interactive echo needs ≥ 100-tick wakes in
   the literal sense the brief means: a 4-token step is 35 ticks and a W = 4 wake is 140 ticks (905 µs). §8's
   connected mode must be restated; the "echo ≈ 0.2–0.4 ms, feels immediate" row is wrong by 4× even at
   W = 1, and typing latency must be stated as **hidden by human key rate (~10 chars/s = 100 ms/token vs
   0.23 ms of work per 4 tokens)**, not as a fast wake.
2. **`NEXT` dominates (≥ 50 %) — TRUE: 49.3 % `NEXT` alone, 90.9 % `NEXT` + dispatch head.** The interpreter's
   dispatch loop is the optimisation target. But the *reason* is not the `switch` or the jump table (44.1 +
   28 = 72 cycles, 6.7 %); it is that `NEXT` fetches the 32-bit token through the byte-wise accessor. Token
   threading would **not** help more than D7 — it would keep the same `rd32` per fetch. That is a correction to
   the brief's inference, and the honest ordering is D7 first, inlining second, threading third.
3. **Byte-wise `@`/`!` more than doubles a *dispatch* — FALSE as stated (1.43×), TRUE for the primitive
   (8.0×/5.5×).** Because `NEXT` already costs 976.5, a 452-cycle accessor inside a handler adds 42 %. But the
   same accessor *is* `NEXT`, twice per dispatch, so D7 remains **first**: doing it takes the dispatch from
   1 074 to 218 (4.9×) and the 505-dispatch token from 28.6 ms to 5.8 ms. The criterion's spirit is met with a
   sharper number than it asked for.
4. **505-dispatch token exceeds a 22-tick wake by more than 10× — TRUE, by 201×** (4 424 / 22). The dispatch
   budget must be the primary limit, and the factor is 201, not "10×".

### 3.1 Which component dominates

`NEXT` **and** its two `rd32` calls: 904.4 of 1 074 cycles (84 %) is the two 32-bit token fetches, 72 cycles
(6.7 %) is the `switch`, and 97.5 (9.1 %) is the primitive. Of the 904: 792 is bookkeeping (bounds check,
address build, prologue/epilogue, 6 call/return pairs) and only **69 is the 8 byte loads themselves**. The D7
estimate of "≈ 69 cycles against 8.1" was right about the loads and wrong about the total: a byte-wise 32-bit
read really costs **452**, 6.5× more than the hand-counted 8 × 8.6.

### 3.2 Why the previous ticks figures were wrong

§8's "one token ≈ 10² cycles ⇒ 16 tokens in ~32 ticks" assumes ~170 cycles/token. The measured figure is
1 074 — 6.3× higher — and the error is entirely the accessor call chain, which C-source counting cannot see:
`TOS = rd32(TOS)` looks like one load and compiles to 432 instructions-worth of work through three call frames.

### 3.3 What is not in these numbers

* **`word()` + `find()` per token** (parse, upper-casing into PAD, dictionary walk with byte-wise `rd8`/`rd16`
  and a `rd32` per header). It is *not* a dispatch, so it is outside the brief's question, but it is
  byte-wise work on the same 450-cycle accessor and will dominate any non-dispatch token cost. Any "cycles per
  token including parse" claim needs a second accounting; §8 must not imply 1 074 is the whole token cost.
* **Overlap.** P05's 4.0 cycles/instruction is a retire interval from a dependent chain; a superscalar or
  store-buffered overlap could shave 10–30 % off paths with independent work. The conclusions are ratios and
  orders of magnitude, and none of the four criteria is near its threshold except #3, which is discussed
  explicitly.
* **Icache/IFETCH misses** beyond the flat 4 cycles/instruction already measured.

### 3.4 Sanity check against P05's own numbers

P05 §1 says a 1-tick wake has "41 cycles ≈ 10 dependent ALU ops or 5 RTC RAM loads of actual work". At 1 074
cycles a dispatch, 41 cycles is **4 % of one dispatch** — the 22-tick floor (2 697 c) is 2.5 dispatches. This
probe adds no new measurement, but the two are consistent: P05's instruction costs are the correct building
blocks and dispatch cost was the missing multiplier, exactly as the brief's "nobody multiplied them".

---

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §5 — "Per-wake arithmetic" bullet: append after the existing sentence

> **Per-dispatch arithmetic** (P14, static accounting of the P02 32-bit `uforth.c` at the costs above):
> one primitive dispatch costs **976.5 cycles before the primitive runs** — `NEXT` 480.2 + dispatch head
> 496.3 — and **1 006 / 1 074 / 1 506 cycles** best / typical / worst including the handler, because `NEXT`
> performs **two** byte-wise `rd32` fetches per token (token → xt → code field) and each `rd32` is **452
> cycles**: 18 instructions plus two `rd16` calls plus four `rd8` calls, of which only 34 cycles are the four
> `lbu`s. So **`NEXT` is 90.9 % of a dispatch and the primitive is 9.1 %**. A 22-tick wake (2 697 cycles)
> retires **2.5 dispatches, not 4 tokens**; a 4-token typing step is **35 ticks (226 µs)**; P04's 505-dispatch
> token is **4 424 ticks (28.6 ms) = 201× the floor and 953× the 30 µs connected budget**. With D7 (native
> `lw`/`sw`) the same dispatch is **218 cycles** and the 505-dispatch token **898 ticks (5.8 ms)** — still
> 20× the floor, so *both* D7 and a dispatch budget are required, and the budget is `p ≤ 12` per 22-tick wake
> (2 697 / 218) before any parse cost.

### 4.2 `docs/01-proposal.md` §8 — replace the two sentences after the table

Current text (to be replaced): *"The connected period is **not** 1–4 ticks: … so a wake that retires 16 tokens
needs ~32 ticks. That is the derivation the earlier "7–30 µs" figure got wrong by assuming 136 kHz and no wake
overhead."* and the table row *"**Connected** | 32–64 ticks (207–414 µs) | 3.8–7.8 k cycles | terminal
attached; echo ≈ 0.2–0.4 ms, feels immediate"*.

> | Mode | Period | Work per wake | Behaviour |
> | --- | --- | --- | --- |
> | **Connected** | 140 ticks (905 µs) at `k = 4, W = 4`; 35 ticks (226 µs) at `k = 4, W = 1` | 17 184 cycles | terminal attached; 16 tokens/wake; echo of a 4-token step is 226 µs |
> | **Autonomous** | 100 ms (≈ 15 500 ticks) | 1.9 M cycles | terminal gone; tasks and events keep running |
> | **Idle** | 1 s | 19 M cycles | waiting on a GPIO event or a mailbox poke |
>
> The connected period is set by the **dispatch cost**, not by the tick floor: a primitive dispatch is
> **1 074 cycles (8.8 ticks)** and `NEXT` alone is 480.2 of it (P14). A `k = 4` step of ordinary typing is
> therefore **35 ticks (226 µs)** and one wake of `W = 4` steps is **140 ticks (905 µs)** — 4× the previous
> "0.2–0.4 ms" claim and 6× the ~32-tick estimate that assumed ~170 cycles/token. The 22-tick floor (142 µs)
> is no longer the binding constraint for typing; it is exceeded by the work. **What makes typing feel
> immediate is not the wake period but the human key rate**: at 10 chars/s one token arrives every ~100 ms,
> and its 8.8 ticks of work are 0.23 % of that interval. The echo claim must be "feels immediate because
> typing is slow", not "feels immediate because the wake is 0.2 ms". P04's 505-dispatch token does **not** fit
> any connected period (28.6 ms today, 5.8 ms after D7), which is why the dispatch budget in §5 is mandatory
> rather than prudent.

### 4.3 `docs/03-prototype-review.md` D7 — amend the second sentence and add a paragraph

Current text: *"Measured (P05, on the board): a byte load costs **8.6 cycles**, a native `lw` **8.1**, so a
`rd32` cell read costs **≈ 69 cycles against 8.1** — an **8.5× penalty**."*

> Measured (P05, on the board): a byte load costs **8.6 cycles**, a native `lw` **8.1**. But the 8.6 is only the
> load: P14 compiled the accessor and disassembled it, and a `rd32` cell read costs **452 cycles against 8.1**
> — a **56× penalty**, not 8.5× — because the four `lbu`s are 34 of those cycles and the other 418 are the
> bounds check, the address arithmetic and **three levels of call/return** (`rd32 → rd16 → rd8`, 18 + 2 × 20 +
> 4 × 8 instructions with prologue/epilogue at every level). In context: `@` through the accessor is 517 cycles
> against 64.9 for a native `lw` (**8.0×** per primitive), and — the part that reorders the plan — `NEXT` calls
> `rd32` **twice per dispatch**, so the accessor is **84 % of every primitive dispatch** (904 of 1 074 cycles)
> and the "optimisation target" is the accessor, not the primitives and not token threading. **D7 is first, and
> is worth 4.9× on dispatch cost (1 074 → 218) and 4.9× on the 505-dispatch token (28.6 ms → 5.8 ms).** A
> one-line `static inline` on the accessors, without changing them to `lw`, is worth 3.1× on the accessor (452 → 146) and 2.2× on the dispatch (1 074 → 486) and
> should be done in the same change; after D7 `NEXT` is still 55 % of a dispatch, so the *second* item is the
> dispatch loop (inline `NEXT`, keep `cf` in a register), and token threading is third.

---

## 5. Follow-ups

1. **Account the parse.** `word()` + `find()` costs per token is missing and is byte-wise heavy (a `rd32` per
   dictionary header, byte-wise name compare). Until it is weighed, §8's "cycles per token" is a lower bound.
   ~20 min with the same method.
2. **Re-run the accounting after D7 and after `static inline`** — the 218-cycle dispatch in §1.2 is derived
   by re-weighting the same listing, not by compiling a D7 build. A second disassembly of the fixed accessors
   would confirm it for the price of one compile.
3. **This is a model, not a measurement.** Every number is P05's class costs applied to P14's instruction
   counts; one `rdcycle` run of the same four paths on the board (P05's harness already exists) would settle
   the ±30 % overlap question and the 452-cycle `rd32` directly. It is cheap and it is the only way to catch a
   systematic error in the per-instruction model.
4. **Dispatch budget arithmetic to carry into §5:** at 218 cycles/dispatch (post-D7) a 22-tick wake retires
   `2 697/218 = 12` dispatches; at 100 ticks, 56; at the 140-tick connected wake, 78. P04 proposed `p = 32`,
   which needs a 70-tick (452 µs) wake post-D7 — pick `p` and `W` together.
