# P54 — Idea 4, variable-length tokens: **NO-GO**, measured

Question (falsifiable): can the hottest words compile to **1 byte** instead of 2, so the baked code area
falls and the freed bytes become application space?

**Answer: no.** The prize is bounded by the number of tokens that exist in the code area — **118 of them,
118 B absolutely, 44 B achieved** — and the cost of reading and writing the encoding is **+352 B of pool**
(`.text` +348, `.bss` +4). At the shipping `MEMSZ` 1400 the variant **does not link at all** (the ULP's 8 KiB
RAM region overflows by 13 B of `.bss`); priced at a `MEMSZ` where it does link, application space falls
**354 → 49 B**.

The idea's premise was wrong in a way only a census could show: "~80 % of dynamic tokens are 1 byte" is
**true** (measured 65–85 %) and **irrelevant** — the bytes saved are a *static* property, and the baked
prelude contains 118 tokens in 522 B of code. 150–200 B was never available. It is also not enough: even a
*free* encoder would leave a `+64 B` decoder against a `44 B` prize.

Everything below is host-only. No `/dev/ttyACM*`, no flash, no `idf.py`; `probe/repl/build` untouched.

---

## 0. Method, and the twin-build self-check

`./measure.sh <name> [cflags]` compiles `src/ulp_repl.c` (which `#include`s `src/uforth.c` and the baked
`src/image.h`) with the **shipping** ULP compile command from `probe/repl/build/esp-idf/main/ulp_main/`
`compile_commands.json`, and links with the **shipping** link line out of `build.ninja`, minus our own object.
Sizes are `riscv32-esp-elf-size -A` on the ELF, per-symbol sizes are `nm -S`.

The baseline must reproduce the flashed image before any delta is believed:

```
$ ./measure.sh base
base        elf .text=5252  .rodata=308  .data=1416  .bss=877 | obj .text=6106 .rodata=308 | sha=5e9434a7c6096071

$ riscv32-esp-elf-objcopy -O binary --only-section=.text <shipping ulp_main.elf> out/ship.text
$ sha256sum out/ship.text out/base.text
5e9434a7c609607128949f1741f0af0e1ba207ab31a04ef5980da676a3e0a7f1  out/ship.text
5e9434a7c609607128949f1741f0af0e1ba207ab31a04ef5980da676a3e0a7f1  out/base.text
```

The twin *is* the flashed image, byte for byte. Every one of my edits is behind `-DP54_TOK`, so this check
still passes at the end of the work (§6).

Two new tools, both independent of the engine's own decoder (a verifier that shares code with the thing it
verifies cannot catch a decoder bug):

* `tools/tokcensus.py <image.h> <names.log>` — walks `mem[]` definition by definition, with the operand
  widths the dispatch switch actually uses, and counts tokens. The xt→name map is dumped **by the bake
  itself** (`-DP54_NAMES`, one `NAME` line per header from `mkhdr_pad`, the one place a name becomes a
  header); a regex over the prelude would be a second derivation of the vocabulary (R6).
* `tools/tokverify.py <mode> <image.h> <names.log> <mode> <image.h> <names.log>` — decodes two images into
  normalised instruction sequences and diffs them definition by definition, resolving branch operands to
  (definition, step) so a changed layout does not read as a changed program. `base` and `p54` modes.

Both validate their own input: the census fails if the cell walk does not cover the code area byte for byte
(`522 of 522`), if a code field disagrees with the name log, or if a primitive owns more than its code field.

---

## 1. Headroom, measured from the baked image (not estimated)

`./tools/bake.sh 1400` then `tools/tokcensus.py`. Shipping image, `MEMSZ` 1400:

```
image out/image_names.h: MEMSZ 1400, code area 578 B [DICT 56..578), V_LATEST 932, HDRTOP 1272
words 85 (immediate: 13), code-area bytes 522 of 522: code-field 170 B, operand 116 B, token 236 B
tokens 118: emitted by cw() 112, by the prelude's W, (BRANCH/0BRANCH) 6
```

**The code area is not mostly tokens.** Of `V_HERE` 578 B: 56 B of system variables, 170 B of code fields
(85 words × 2), 116 B of inline data (26 LIT cells + 6 branch operands), and **236 B of tokens (118)**.

Token frequency over the whole baked code area (hottest first):

| token | n | | token | n | | token | n |
|---|---|---|---|---|---|---|---|
| LIT | 26 | | 0= | 3 | | OR | 1 |
| EXIT | 18 | | + | 3 | | ! | 1 |
| SWAP | 11 | | EMIT | 3 | | = | 1 |
| W, | 10 | | BRANCH | 2 | | < | 1 |
| HERE | 7 | | LATEST | 1 | | /MOD | 1 |
| - | 7 | | W! | 3 | | >R | 1 |
| DUP | 5 | | 0BRANCH | 4 | | R> | 1 |
| @ | 4 | | DROP | 4 | | | |

23 distinct token targets out of 85 words. 6 of the 118 tokens (BRANCH/0BRANCH) are emitted by the
prelude's `W,` as raw 2-byte cells; the other 112 go through `cw()`.

### Theoretical best case

| scheme | 1-byte-able tokens | best case |
|---|---|---|
| A: code = primitive id (`cf ∉ {DOCOL,DOVAR,DOCON}`) | 109 of 118 | **109 B** |
| B: code = code-area halfword index, first 256 B | 117 of 118 | **117 B** |
| any encoding at all, every token 1 byte | 118 of 118 | **118 B** |

**118 B is the ceiling, and it is a ceiling on the *whole idea*, not on my implementation.** The proposed
150–200 B would need 150–200 tokens in the code area; there are 118.

### Dynamic mix (the premise, measured)

`-DP54_MIX` counts tokens as they execute, one counter per fetch path (bench-only build):

| workload | 1-byte-code-eligible | 2-byte xt | eligible |
|---|---|---|---|
| arith | 17 293 | 3 086 | **84.9 %** |
| matrix | 24 267 | 6 582 | **78.7 %** |
| memory | 978 | 260 | **79.0 %** |
| recursion | 3 960 | 2 170 | 64.6 % |
| prelude load | 140 | 51 | 73.3 % |

So "≈80 % of dynamic tokens" is right. It buys nothing: the code area is a *static* size.

---

## 2. The design that was built (and the two things that nearly killed it)

A 1-byte code must share `mem[]` with 2-byte xt tokens, and every stream read is `rd16_paged()` at an even
address. **Making `ip` odd is not available**: `rd16()` on an odd address is a misaligned halfword load and
traps on this core, so a byte-granular stream would turn "wrong answer" into "dead machine" — and it is
unverifiable on the host, so the design forbids it.

One cell (little-endian u16), read with the same load the engine always used:

```
cell & 1   == 0      a plain token: the xt itself (xts are even; mkhdr_pad rejects an odd one)
cell & 1   == 1      low byte is a code:  cf = (cell & 0xfe) >> 1
cell & 0x100 == 1    high byte is a second code: cf = cell >> 9, dispatched after the first
cell & 0x1ff == 1    lone code; the high byte is filler and never executed
```

A code is a **primitive id**, so dispatching one skips the `rd16_paged(w)` code-field load entirely — the
code *is* the code field. That is scheme A, and it is why a code may only name a primitive that does not read
`w` (DOCOL/DOVAR/DOCON derive an address from it and keep the 2-byte form). Scheme A was chosen over scheme B
because it also shrinks *app* code (§5), which B cannot.

### 2.1 The trap I fell into: `HERE` must point at the next token

First implementation packed in place: emit `[code][0]` at `HERE`, keep a `t_free` pointing at the unused high
byte, and fill it if the next token is also a code. The saving looked better (50 B) and the prelude still
compiled — then `2 3 + 4 * .` printed nothing and the bake of `line.fs` died with `ERR_STACK`.

`tokverify.py` named it in one line: the `REPEAT` operand pointed at **500** where `BEGIN`'s `HERE` was
**498**. With a half-used cell, `V_HERE` is one byte past the next token's real address — so every branch
target the prelude computes with `HERE` (`BEGIN`, `IF`, `THEN`, `ELSE`, `WHILE`, `REPEAT`) is a byte late, and
the loop re-entered the middle of a paired cell. The `.` word is exactly where it shows.

Fix: **the compiler holds one token back** in a C variable and only writes a cell when it knows both codes.
`V_HERE` then only ever moves when a whole cell is written, so every `HERE`-based target stays exact. Cost of
the fix: 50 → 44 B. This is the one failure mode that would have been invisible without an independent
decoder — a golden-file diff would have shown `ERR_STACK` three words away from the cause.

### 2.2 The trap the design must not have: a code that leaves the stream

A code in the **low** half of a cell leaves its partner *pending*; if the low primitive leaves the stream
(EXIT pops `ip`, BRANCH/ZBRANCH/LOOP set it, PAUSE/FAULT swap the whole machine) the pending code belongs to a
stream the machine has left. `t_leaving()` pins that set; such a code may sit in the **high** half only, where
it runs last and leaves nothing pending.

Measured consequence of omitting it (mutation, §4): `0 T3 .` printed `111CC` — the unreachable `67 EMIT` after
a *nested* `EXIT` ran. Note the sub-lesson: at the **outermost** level the `if (!ip)` check returns to C before
a pending code is consumed, so a top-level test masks the bug. `tests/tok.fs` T3 wraps the word in another
colon definition for that reason, and the first version of T3 (un-nested, `EXIT THEN`) let the mutation
**survive** — recorded here because that is the difference between a test and a decoration.

### 2.3 Branch operands, the number-first path, the checkpoint: untouched

The five dangers the task named, answered one by one:

1. **Branch operands.** Not touched at all, deliberately. `IF`/`THEN`/`BEGIN`/`UNTIL`/`WHILE`/`REPEAT` keep
   emitting their token with `W,` (a raw 2-byte xt cell) and their operand with `W,`, and `P_ZBRANCH`'s
   `ip += 2` skip is unchanged. The operand is still the fixed 2-byte cell immediately after the token, and
   the backpatch (`THEN`, `REPEAT`) still writes at `HERE`-derived even addresses. All 6 branch tokens stay 2
   bytes; that is 6 B of prize given away on purpose, for a whole class of stride bug not entered.
2. **`HERE`/`LATEST`/compiled addresses.** §2.1 — this was the real hazard, and it is closed by making
   `V_HERE` mean the same thing it always meant.
3. **P46's number-first path and `find()`.** `find()` unchanged. The numeric path gained one thing: `clit()`
   flushes the held-back token (and pairs with it when it can), because LIT's operand must follow LIT's cell.
   `tokverify.py` confirms every LIT cell's operand value is unchanged.
4. **The checkpoint `(w, ip)`.** Unchanged, and the `VM` struct is byte-identical (`.bss` +4 B is one static,
   `t_pend`). `ip` is still a byte offset into `mem[]` and is still even at every fetch; `w` still carries
   the xt for xt-form tokens (a code token needs no `w`, which is why DOCOL/DOVAR/DOCON are excluded).
5. **The baked image.** Re-baked by the same `ctok()` on the host and on the chip (one definition, no second
   encoder), and `tokverify.py` proves the encoded image decodes to the shipping image's instruction
   sequence, definition by definition, with branch operands resolving to the same positions.

---

## 3. Measured variants

All rows `.rodata` unchanged at 308 B. `.data` is `MEMSZ + 16`, so it is quoted at the `MEMSZ` the row was
measured at.

| variant | what changed | `MEMSZ` | `.text` | Δ`.text` | `.bss` | Δ`.bss` | code area | tests | bench |
|---|---|---|---|---|---|---|---|---|---|
| `base` | shipping | 1400 | **5 252** | — | 877 | — | 578 | 11 PASS | 5 PASS |
| `base1200` | same engine, paired measurement point | 1200 | 5 252 | — | 877 | — | — | — | — |
| `toknp` | **decoder only** (`-DP54_NOPAIR`: two token forms understood, encoder never emits one) | 1400 | 5 410 | **+158** | 881 | **+4** | 578 (0) | 11 PASS | 5 PASS |
| `tok` | decoder + encoder + prelude re-bake | 1200 | **5 600** | **+348** | 881 | **+4** | **534 (−44)** | **11 PASS** | **5 PASS, identical** |
| `tok` | the same at the shipping `MEMSZ` | 1400 | — | — | — | — | 534 | — | **does not link** |

The `MEMSZ` 1200 rows exist because the full variant does not link at 1400 (see below); they are a *paired*
measurement (`base1200` vs `tok1200`), which is what Δ`.text` needs. `src/ulp_repl.c`'s `#define MEMSZ` is now
`#ifndef`-guarded for exactly this: a link that fails on `region ram overflow` prints no section sizes, and
"it needs N more bytes than the pool has" is a better answer than "it did not fit". Without `-D` nothing
changes, so the twin still reproduces the shipping hash.

`toknp` (the decoder with no codes emitted) *does* link at 1400 — and is **159 B over the pool**
(5 410 + 308 + 1 416 + 881 = 8 015 of 7 856). It buys nothing at all, so at the `MEMSZ` it would need
(1 241) application space is 195 B instead of 354 B.

The link failure at the shipping `MEMSZ`:

```
ld: address 0x200d of out/tok1400.elf section `.bss' is not within region `ram'
measure: link of tok1400 failed
```

`0x200d` = 8 205 > 8 192 B of RAM; the pool limit is the tighter 7 856 B.

### 3.1 Where the 348 B goes (`nm -S`, per symbol)

| symbol | base | `toknp` | `tok` | Δ (`tok`) |
|---|---|---|---|---|
| `vm_enter` (the dispatch loop) | 2 782 | 2 836 | 2 842 | **+60** |
| `main` (interpret/`clit` caller, inlined) | 882 | 916 | 950 | +68 |
| `clit` | 34 | 32 | 76 | +42 |
| `t_emit` | — | 32 | 50 | +50 |
| `t_pair` | — | — | 52 | +52 |
| `t_kind` (with `t_leaving` inlined) | — | — | 54 | +54 |
| `t_flush` | — | 20 | 20 | +20 |
| `cw`, `find`, `word`, `wr16` | 30/58/172/66 | same | same | 0 |

**The decoder is cheap; the encoder is not.** +60 B on the hot path, +288 B in the compiler. The decoder's
+60 is two extra conditional branches and 2–3 ALU ops per fetch (§7 says what that is worth in cycles). The
compiler's +288 is the price of deciding, for every compiled token, which of three forms applies — and of
being *called* rather than inlined at `-Os`.

---

## 4. Validation

### 4.1 Suite and bench, variant and base

```
$ ./tests/run.sh                                   -> 11 PASS
$ P54_EXTRA=-DP54_TOK ./tests/run.sh               -> 11 PASS
$ ./bench/run.sh                                   -> 5 PASS   (prelude baseline 261)
$ P54_EXTRA=-DP54_TOK ./bench/run.sh               -> 5 PASS   (prelude baseline 261)
```

`bench/run.sh` compares **checksums, DISP and limits** exactly; the variant reproduces every number:

| workload | result | dispatches |
|---|---|---|
| arith | 832501 | 15 163 |
| matrix | 67000 | 25 651 |
| recursion | 144 | 5 230 |
| memory | 120 | 862 |
| depth | 0 ERR_STACK | — |

Identical DISP is not a formality: it says the encoded image executes **exactly the same number of
dispatches**, which is what a correct decode of a 1-byte code inside a paired cell has to produce. It also
caught a bug in my instrumentation — with `p42_dispatches` incremented before the dispatch label, every code
token went uncounted and DISP read 5× low (261 → 145 on the prelude alone). The counter now sits after the
label, so it counts once per dispatch on both paths.

Two test-harness changes, both deliberate:

* `tests/suite.fs` printed **`HERE`**, i.e. the absolute code size, so any change to the code area fails the
  suite and the obvious "fix" is to regenerate the golden — the reflex `run.sh` warns about. It now asserts
  the invariant (`56 HERE < .` and `HERE LATEST < .`) instead; the code size keeps its one owner,
  `tools/bake.sh` (R7). This made the golden layout-independent for **both** builds, and the base suite stays
  green.
* `tests/run.sh` and `bench/run.sh` take `P54_EXTRA` so a variant runs on the same script that defines the
  suite, instead of a hand-copied gcc line (R9).

### 4.2 The new test, `tests/tok.fs` — and its four mutation tests

Six lines, one per way the encoding can fail: a pair runs low-then-high (T1), a branch target landing on a
paired cell starts at the low code (T2), a mid-body `EXIT` does not run its cell partner (T3), `['] w EXECUTE`
still dispatches a code field (T4), an immediate word emits *after* the token before it (T5), a number after a
code keeps its own cell (T6). The golden is derived from the **shipping** engine, and the variant reproduces it
byte for byte.

Each mutation was driven through the engine, not reasoned about:

| mutation | expected failure | measured |
|---|---|---|
| `t_kind`: leaving rule removed | T3 runs the unreachable `67 EMIT` | `2512111ERR_STACK` (want `2512111022253!4212-1`) |
| `t_pair`: the two codes written in the wrong order | T1/T2 wrong | `  DERR_STACK` |
| `interpret`: no flush before an immediate word | T5 / the prelude's own `.` | `ERR_STACK` — the prelude does not even run |
| *(first T3, `EXIT THEN`, un-nested)* | — | **mutation survived**; T3 rewritten with `EXIT 67 EMIT` inside `: T3 T3X ;` |

### 4.3 The image really is the same program

```
$ python3 tools/tokverify.py base out/img_base_p.h out/n_base_p.log p54 out/img_tok_p.h out/n_tok_p.log
A out/img_base_p.h mode=base: code area 578 B, 85 words
B out/img_tok_p.h  mode=p54 : code area 534 B, 85 words
definitions compared: 85, steps total 186, mismatching: 0
B encoding facts: 86 1-byte codes, 22 of them in paired cells, 42 lone, 32 2-byte xt tokens
OK: both images decode to the same instruction sequence
```

---

## 5. Net bytes — the arithmetic that decides it

```
prize   = code area 578 -> 534                      = -44 B   (measured, MEMSZ 1400 bake)
cost    = .text +348 + .bss +4                      = +352 B  (measured, ELF sections)
pool    = 5 600 + 308 + 1 416 + 881 = 8 205 of 7 856      = 349 B OVER
```

The pool is at 7 853/7 856 today, so every one of those 352 B has to come out of `MEMSZ`, and `MEMSZ` is
application space 1:1:

| | base | variant |
|---|---|---|
| `MEMSZ` that fits the pool | 1 400 | 1 051 (= 1 400 − 349) |
| `BLKADR` = `MEMSZ` − 128 | 1 272 | 923 |
| `V_LATEST` (`HDRTOP` − 340) | 932 | 583 |
| `V_HERE` | 578 | 534 |
| **application space** | **354 B** | **49 B** |

And at `MEMSZ` 1 051 the two engines differ by exactly the prize: `V_LATEST` is 583 either way (`HDRTOP`
923 − 340 headers), so the base engine would have `583 − 578 = 5 B` of application space and the encoded one
`583 − 534 = 49 B`. **In practice the variant does not fit the pool at all at `MEMSZ` 1400; at the `MEMSZ`
where it does, application space is 49 B instead of 354 B** — the 44 B of saving is spent eight times over on
the 349 B of pool the encoding costs.

Two bounds worth keeping, because they are independent of how clever the implementation is:

* **Decoder alone** (`toknp`: understand both forms, emit neither) costs **+158 B text, +4 B bss = 162 B of
  pool** for **0 B** of prize — 159 B of application space, since the pool is full. Even a free encoder cannot
  save the idea.
* **The whole ceiling** is **118 B**. The cost is 3× the ceiling, 8× the measured prize.

### The one thing the scheme does buy: program density

Scheme A codes primitives at *any* xt, so application code shrinks too (measured by dumping the code area
after loading each workload at `MEMSZ` 2048):

| workload | app code, base | app code, `tok` | |
|---|---|---|---|
| arith | 60 B | 46 B | −23 % |
| matrix | 192 B | 172 B | −10 % |
| recursion | 42 B | 38 B | −10 % |
| memory | 214 B | 192 B | −10 % |

Real, and irrelevant at this scale: to amortise 352 B of fixed cost you would need 1 500–3 500 B of
application code, on a machine with 354 B of application space.

---

## 6. Verdict: NO-GO

**Named blocker:** the encoding costs **352 B of pool** and saves **44 B of code area**; the pool is 3 B from
full, so the variant does not link (`.bss` ends at `0x200d`, past the 8 KiB RAM region), and priced at a
`MEMSZ` that would fit, application space falls to **49 B**. The prize is capped at **118 B** by the number of
tokens in the code area — the 150–200 B that motivated the idea does not exist.

State of the tree: everything is behind `-DP54_TOK`; with the flag off `./measure.sh base` still reproduces the
shipping `.text` (`5 252`, `sha=5e9434a7c6096071`), `tests/run.sh` is 11 PASS, `bench/run.sh` 5 PASS, and
`tools/bake.sh 1400` reproduces the current `src/image.h` **byte for byte** (checked with `cmp`).

### What would have to change for this idea to be worth anything

1. **~3× more tokens in the baked code area** (≈350, i.e. a prelude 3× the size of today's) for the ceiling to
   approach the fixed cost. Growing the dictionary costs 4 B/word of headers, so the app space pays twice.
2. **Or an 8× smaller encoder+decoder** (< 44 B total). The decoder is already only +60 B; the compiler is
   +288 B, and it cannot get much cheaper: it must classify every token (`t_kind`/`t_leaving`), and at `-Os`
   the helper calls are not inlined. A 2-word bitmask would replace `t_leaving` (≈30 B → 8 B of `.rodata`),
   i.e. maybe 100 B of the 288 — still 2× the prize.
3. **Or pair across the prelude's immediates.** Token order allows 46 pairs (92 B); the compiler achieves 22
   (44 B) because every immediate word (`IF`/`THEN`/`ELSE`/`BEGIN`/`UNTIL`/`WHILE`/`REPEAT`) must flush the
   held-back token before it writes to `HERE`. Recovering the rest means the prelude's immediates stop using
   `W,` and become token-aware emitters, i.e. changing the exact code that P38 already paid for with a hang.
   Even a perfect 92 B is under the 352 B cost.
4. **Operands are the bigger untapped pool** (116 B of the 522 B code area, all 2-byte cells holding values
   < 256 in this image) — a small-literal form would be worth ≤26 B. Same order of magnitude; not the answer.

---

## 7. What I could not measure, and one thing I could not close

* **Cycles.** The host cannot answer this (R8). The variant *removes* one halfword load per coded token and
  *adds* ~2 conditional branches plus 2–3 ALU ops per fetch, so the sign of the cycle delta is genuinely
  unknown: E-053 measured ~24 cycles per instruction with no cache to hide it, and the load it removes is the
  same one that made `rd16` worth 618 cycles/dispatch for two tokens. A board run with `rdcycle` would settle
  it; **it is not needed for the verdict**, because the byte accounting already decides the question.
* **Misaligned loads.** The design avoids odd addresses *without* ever testing what this core does with an odd
  `rd16`; only the board could confirm the trap, and the design deliberately does not depend on the answer.
* **`MEMSZ`-independent `.data`.** `.data` is `MEMSZ + 16` in every row, so the 44 B of code-area saving never
  appears as a section delta — it appears as application space (`V_LATEST − V_HERE`). Quoting a section delta
  for it would be quoting zero.
* **Why `tok` had to be priced at `MEMSZ` 1200.** At 1400 the link fails on the RAM *region*, so no section
  sizes exist for the row; the paired 1200 measurement is the only honest way to quote Δ`.text`. The pool
  arithmetic in §5 uses the 1400 figures (`.data` 1 416) and does not depend on that shift.

---

## 8. Files

| file | state |
|---|---|
| `src/uforth.c` | the variant, entirely behind `-DP54_TOK` / `-DP54_NOPAIR` / `-DP54_MIX`; `-DP54_NAMES` host-only name dump |
| `src/ulp_repl.c` | `#define MEMSZ` is `#ifndef`-guarded so a non-fitting variant can still be priced |
| `src/image.h` | **unchanged** (`cmp` against the pre-work bake) — nothing to re-bake, the idea did not ship |
| `tests/run.sh`, `bench/run.sh` | take `P54_EXTRA` |
| `tests/suite.fs`, `tests/suite.expected` | absolute `HERE` replaced by an invariant (R7) |
| `tests/tok.fs`, `tests/tok.expected` | new: the encoding's six failure modes, mutation-tested |
| `tools/tokcensus.py` | new: static token census from a baked image |
| `tools/tokverify.py` | new: two images decode to the same program |
| `bench/` | copied from `probe/repl/bench` (unchanged), plus the frozen baseline |

Diff shape (192 lines added to `src/uforth.c`, 10 to `src/ulp_repl.c`): the encoder is `t_kind`/`t_leaving`/
`t_emit`/`t_pair`/`t_flush`/`ctok`/`clit` (≈60 lines) and `interpret`'s flush points (≈10); the decoder is the
labelled dispatch entry and six lines at the bottom of `vm_enter`'s loop; the rest is the block comment that
records the two traps.
