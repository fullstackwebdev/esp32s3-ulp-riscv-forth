# P54 — is a table-driven kernel cheaper than 10 hand-written primitive bodies?

**Answer: yes, but the premise in TASK.md over-counts.** Exactly **10** primitive bodies are genuinely
same-shape (`pop b; top = op(top, b)`), not 15–20. Those 10 bodies are **398 B**, they are replaced by a
**46 B** shared body + **72 B** of per-op leaves/trap, and the measured result is

| | measured |
| --- | --- |
| `.text` | **5 252 → 4 972 B (−280)** |
| `.rodata` | 308 → 364 B (**+56**) |
| **pool** (sum of sections) | **7 853 → 7 629 B (−224)** |
| dictionary (`mem[]`, the baked image) | **byte-identical** — no primitive removed or changed |
| `tests/run.sh` | green (11/11, incl. a new `binops.fs`) |
| `bench/run.sh` equivalents | identical results **and** identical DISP on all five workloads |

The "constant" the task asked for first: **reshaping one body into the kernel form measures 0 bytes**
(`-DP54_BINOPS=1`: `.text` 5 252, pool 7 853). That row is a *compiler artefact and not the kernel's
price*: with a one-entry `static const` table and a known index, GCC folds the indirect call back into a
direct call and inlines it, so `p54_op_ADD` and the table do not even exist in the object (`nm` shows no
`p54_*` symbol, `vm_enter` is 2 782 B, and the `+` body is the original 16 instructions at a different
address). The first rung where the kernel actually exists is **rung 2**: `p54_binops` 8 B + two 4 B leaves,
Δ`.text` −6. Measured one-off cost of the shared machinery across the rungs: **66 B** (rung 2), 64 B
(rung 3), 58 B (rung 5), **46 B** (rung 10) — i.e. 1.2–1.7 bodies, paid once, and every word after it
saves its whole 38–44 B body minus a 4–10 B leaf. The win is per-body × (n − 1), which is why the *count*
matters more than the kernel price.

Board untouched: no `/dev/ttyACM*`, no flash, no `idf.py`. Everything below is a host/compiler measurement.

---

## 1. Method — the twin build, and the proof it is the shipping machine

`./measure.sh` (written by agentA, unchanged) compiles `src/ulp_repl.c` — which `#include`s `src/uforth.c` —
with **the command IDF recorded** (`build/esp-idf/main/ulp_main/compile_commands.json`) and links with **the
shipping link line and object list** (`build.ninja`, minus our own object). Our `src/` is a byte-identical
copy of `probe/repl/src/` (`diff -rq` clean), and nothing outside this directory was written.

```
probe/research/P54-ops$ sha256sum out/ship.text out/base.text
5e9434a7c609607128949f1741f0af0e1ba207ab31a04ef5980da676a3e0a7f1  out/ship.text
5e9434a7c609607128949f1741f0af0e1ba207ab31a04ef5980da676a3e0a7f1  out/base.text
```

`out/ship.text` is `.text` of `probe/repl/build/esp-idf/main/ulp_main/ulp_main.elf` (the flashed image,
`.text` 5 252 B, `.rodata` 308, `.data` 1 416, `.bss` 877). **The twin reproduces the flashed code byte for
byte**, so every Δ below is a delta in the real binary. All rows: `RESULTS.txt`; all ELFs and dumps: `out/`.

Re-measured every run, never cached: `./measure.sh <name> [-D flags…]` → `elf .text/.rodata/.data/.bss`,
object `.text`/`.rodata`, and the `.text` sha.

## 2. Step 1 — classification of every primitive body

Sizes are **measured** from the base ELF: the switch's jump table is 71 entries in `.rodata`
(`0x1484..0x15a0`), each entry is a case address, so the distance to the next entry is the body's size
(includes the shared tail jump; a few bodies share a tail, e.g. LOOP/PLOOP 90 and TICK/B[TICK 36 together).

### 2a. Same-shape — `pop b; top = f(top, b)`, nothing else (10 words, 398 B)

| primitive | id | body bytes (base) | leaf bytes (P54) |
| --- | --- | --- | --- |
| `+` ADD | 27 | 40 | 4 |
| `-` SUB | 28 | 40 | 4 |
| `*` MUL | 29 | 40 | 6 |
| `AND` | 32 | 38 | 4 |
| `OR` | 33 | 38 | 4 |
| `XOR` | 34 | 38 | 4 |
| `LSHIFT` | 36 | 40 | 6 |
| `RSHIFT` | 37 | 40 | 6 |
| `<` LT | 39 | 44 | 10 |
| `U<` ULT | 40 | 40 | 10 |
| **total** | | **398** (mean 39.8) | **58** |

Read off the disassembly, not inferred: `+` is `0x960..0x986` = 16 instructions (lbu/addi/zext.b/sb of
`V->SP`, the masked TOS and NOS addresses, two `lw`, the ALU op, one `sw`, one `j`). `LSHIFT`/`RSHIFT`
carry no extra cost for `& 31` — RISC-V `sll`/`srl` already mask the shift count, so the C mask is free.
`<`/`U<` add `slt`+`neg`.

### 2b. Shape-distinct — and the specific reason each one cannot ride this kernel

| group | primitives (body bytes) | why it is a different shape |
| --- | --- | --- |
| two pops, **no** result push | `!` STORE 38, `C!` CSTORE 66, `W!` WSTORE 40 | the stack effect is `( a b -- )`; a `top = f(top,b)` kernel pushes one |
| two pops onto the **return** stack | `(DO)` DO 44 | writes `RS[]`, pops two, pushes none |
| **two results** | `/MOD` 38, `U/MOD` 48 | sets top *and* pushes (q, r), and has `b==0` / `b==-1` special cases |
| unary compute | `INVERT` 22, `0=` 24 | one operand, no pop: `top = f(top)` |
| unary memory | `@` 28, `C@` 24, `W@` 24, `GPIO@` 20, `ADC@` 8 | operand is an address from the stack; `P()`'s `&junk` bound is the semantics |
| stack shuffle / return stack | `DUP` 10, `DROP` 12, `SWAP` 32, `OVER` 8, `ROT` 46, `>R` 24, `R>` 16, `I` 18, `J` 8, `UNLOOP` 12 | permutation or RS access, no ALU result |
| control flow / `continue` | `EXIT` 38, `BRANCH` 14, `0BRANCH` 32, `(LOOP)`/`(+LOOP)` 90, `EXECUTE` 28, `PAUSE` 60, `FAULT` 56 | rewrites `ip`/`w`/`rsp` and can `continue` the loop; PAUSE and FAULT also switch VM |
| inline operand | `LIT` 18, `(.")` 52 | advances `ip` by a payload |
| parsing / defining | `:` 40, `;` 18, `CREATE` 16, `CONSTANT` 10, `'`/`[']` 36, `LITERAL` 24, `."` 246, `\` 42, `(` 36, `,` 44, `W,` 30, `C,` 66, `SOURCE`-ish `KEY` 4, `KEY?` 34, `EMIT` 28, `TYPE` 58, `MS` 20, `WAKE` 4 | read `tib`/`PAD`, call out, or loop |
| dictionary plumbing | `DOCOL` 16, `DOVAR` 10, `DOCON` 12 | one pop or none; frame/address work |
| block layer (p33) | `BLKXFER` 58, `BLOCK` 182, `UPDATE` 12, `SAVE` 50 | mailbox handshake, bounded wait |
| scheduler (p43) | `SPAWN` 58 | parses a name, writes `tsk[]` |

**The task's "15-20 same-shape" is 10.** The extra 5–10 in the estimate are almost certainly the
two-pop-no-push family (`! C! W! C@` etc.) and `INVERT`/`0=`: they *look* like "pop two, compute" but their
stack effects or operand counts differ, which is exactly the partition the kernel cannot cross.

## 3. Step 2 — the constant, measured first (and why rung 1 lies)

`-DP54_BINOPS=1` converts **only `+`**: `.text` **5 252 → 5 252 (Δ 0)**, `.rodata` 308 → 308 (Δ 0), pool
Δ 0, `vm_enter` 2 782 → 2 782. Read literally that says "the kernel is free", and it is wrong: with one
table entry and an index the compiler knows (`case P_ADD` ⇒ `cf - P_ADD == 0`), GCC **undoes the kernel** —
`nm` shows no `p54_binops` and no `p54_op_ADD`, and the `+` body is the original 16-instruction sequence
(lbu/addi/zext.b/sb of `V->SP`, masked TOS/NOS addresses, two `lw`, `add`, `sw`, `j`) at a new address. The
`.text` size is equal and the sha differs (`5fc259867bed1e2a` vs `5e9434a7c6096071`).

**The honest constant is rung 2**, where the table cannot be folded:

| rung | converted | bodies removed | `vm_enter` | one-off kernel cost | measured Δ`.text` |
| --- | --- | --- | --- | --- | --- |
| 1 | `+` | 40 | 2 782 | **folded away by GCC** | 0 |
| 2 | `+ -` | 80 | 2 768 | **66 B** | −6 |
| 3 | `+ - *` | 120 | 2 726 | 64 B | −42 |
| 5 | `+ - * AND OR` | 196 | 2 644 | 58 B | −102 |
| 10 | all | 398 | 2 430 | **46 B** | −280 |

So the shared machinery costs ~1.2–1.7 bodies once, and each further word is worth ~38 B of `.text`
(22.4 B of pool at rung 10). **Below 2 converted words this lever does nothing at all** — a warning for
anyone who tries the shape on three or four words and concludes it is a wash.

## 4. Step 3 — the ladder: 1 → 5 → 10, measured

Two mechanisms were built from **one ordered op list** (`tools/p54_gen.py`) and both were measured. They
differ only in how the shared body selects the operation:

* **`fp`** — a `static const` table of function pointers in `.rodata`; the case body is
  `b = POP(); TOS = p54_binops[cf - P_ADD](TOS, b);`
* **`opsw`** — no call: `px = &TOS; a = *px; switch (cf - P_ADD) { case 0: a = (a + b); … } *px = a;`
  (GCC builds a second jump table for the inner switch, so `.rodata` is the same size)

| variant | flags | `.text` | **Δ.text** | `.rodata` | **Δ.rodata** | `.data` | `.bss` | **pool** | **Δ.pool** | `vm_enter` | suite |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **base** (sha == ship) | — | 5 252 | 0 | 308 | 0 | 1 416 | 877 | 7 853 | 0 | 2 782 | PASS |
| `fp1` | `-DP54_BINOPS=1` | 5 252 | 0 (folded) | 308 | 0 | 1 416 | 877 | 7 853 | 0 | 2 782 | PASS |
| `fp2` | `-DP54_BINOPS=2` | 5 246 | −6 | 308 | 0 | 1 416 | 877 | 7 847 | −6 | 2 768 | PASS |
| `fp3` | `-DP54_BINOPS=3` | 5 210 | −42 | 320 | +12 | 1 416 | 877 | 7 823 | −30 | 2 726 | PASS |
| `fp5` | `-DP54_BINOPS=5` | 5 150 | **−102** | 336 | +28 | 1 416 | 877 | 7 779 | **−74** | 2 644 | PASS |
| **`fp10`** | `-DP54_BINOPS=10` | **4 972** | **−280** | 364 | +56 | 1 416 | 877 | **7 629** | **−224** | 2 430 | PASS |
| `opsw1` | `-DP54_BINOPS=1 -DP54_OPSW` | 5 252 | 0 (folded) | 308 | 0 | 1 416 | 877 | 7 853 | 0 | 2 782 | PASS |
| `opsw5` | `-DP54_BINOPS=5 -DP54_OPSW` | 5 152 | −100 | 336 | +28 | 1 416 | 877 | 7 781 | −72 | 2 682 | PASS |
| `opsw10` | `-DP54_BINOPS=10 -DP54_OPSW` | 4 974 | −278 | 364 | +56 | 1 416 | 877 | 7 631 | −222 | 2 504 | PASS |

`Δ.data` and `Δ.bss` are **0 in every row** — nothing moved into `.bss`, and the baked image is unchanged.

Where the 280 B in `fp10` comes from (all measured, not modelled):

```
removed  10 inline bodies (jump-table walk of the base ELF)   −398
added    one shared body inside vm_enter                        +46
added    10 leaves (4-10 B each, nm -S)                         +58
added    p54_op_unreachable, the named trap for table holes     +14
                                                   .text total  −280
added    p54_binops[14] of 4 B pointers in .rodata              +56  (net pool −224)
```

`fp` beats `opsw` by **2 B** at both rungs. The difference is inside compiler noise, but it is consistent
at 5 and at 10, so the recommendation takes `fp`; `opsw`'s only advantage would be one fewer indirect
call, and its instruction count is the same (see §5). The `fp2`/`fp3` rows carry 8 B / 12 B of `.rodata`
noise that is *other* tables moving (GCC re-splits the outer switch as labels merge), which is why the
rung-2 pool delta (−6) does not equal rung-3 minus rung-2 exactly.

### Where the table's 56 B goes, and why 4 of 14 slots are empty

The index is `cf - P_ADD`, so slot = primitive id offset: `ADD..MUL` = 0..2, `AND..XOR` = 5..7,
`LSHIFT/RSHIFT` = 9,10, `LT/ULT` = 12,13. Slots 3, 4 (`/MOD`, `U/MOD`), 8 (`INVERT`) and 11 (`0=`) are
shape-distinct (§2b) and therefore **holes**: 16 B of `.rodata` bought on purpose, filled with
`p54_op_unreachable`, which halts with code **0x54**. A null entry would be a call to address 0 — i.e.
`DOCOL` — and would silently run a different primitive, the one failure class this engine must not have.
A hole is unreachable by construction *and* loud if the construction is ever broken.

## 5. The dispatch and cycle effect — honest version

**Dispatch count does not change.** `-DP42_COUNT` on the real workloads:

| workload | base | `fp10` | `opsw10` |
| --- | --- | --- | --- |
| arith.fs | 832501 / DISP 15 424 | 832501 / 15 424 | 832501 / 15 424 |
| matrix.fs | 67000 / 25 912 | 67000 / 25 912 | 67000 / 25 912 |
| recursion.fs | 144 / 5 491 | 144 / 5 491 | 144 / 5 491 |
| memory.fs | 120 / 1 123 | 120 / 1 123 | 120 / 1 123 |
| depth.fs | `0` `ERR_STACK` | same | same |
| prelude baseline | 261 | 261 | 261 |

(`prelude_base 261`, arith 15 424−261 = 15 163, matrix 25 651, recursion 5 230, memory 862 — identical to
`bench/baseline.txt`, so this is the frozen reference and not a re-baselined copy.)

**Instructions per converted dispatch rise.** Counted in the disassembly:

| | instructions for one `+` dispatch |
| --- | --- |
| base, inline body | 16 (pop + dual TOS/NOS address + ALU + store + `j`) |
| `fp10`, shared body + leaf | 22 in the kernel + `op` + `ret` = **24** |
| `opsw10`, shared body + inner table | **24** |

So a converted word costs **≈ +8 instructions** (~2 of them the call/return), i.e. the same code stops
being duplicated and starts being dispatched. **Cycles cannot be measured on the host** — the board numbers
(1 139 cycles/dispatch, ~24 cycles/instruction on the ULP with no cache) are the only ones that exist, and
nothing here was run on the board. Expect arithmetic-heavy code to pay roughly +15 % on those dispatches;
expect everything else (memory words, control flow, the REPL) to be unchanged, since their bodies and the
loop head are untouched.

## 6. The resumability contract (P27) is untouched — verified, not asserted

The per-token checkpoint is the loop's `w = rd16_paged(ip); ip += 2;` (plus PAUSE's advance-before-save),
i.e. it writes `V->W`/`V->IP` on **every** token so a switch can resume at the token that has not run.
`fp10`'s loop head and tail are instruction-for-instruction the same as the base build's:

```
base  loop head                     fp10  loop head
61e: li   s4,70                     666: li   s4,70           ; cf <= 70
62a: lhu  s6,130(a5)   ; V->W       672: lhu  s7,130(a5)
634: jal  rd16                      67c: jal  rd16            ; cf = rd16_paged(w)
638: bltu s4,a0,cd4 (default: err)  680: bltu s4,a0,b86
644: add  a5,a5,a4                  68c: add  a5,a5,a4        ; jump table
648: jr   a5                        690: jr   a5

base  loop tail                     fp10  loop tail
10be: lhu  s6,132(s0)  ; V->IP       f7a: lhu  s6,132(s0)
10c8: jal  rd16                      f84: jal  rd16            ; w = rd16_paged(ip)
10cc: addi s6,s6,2                  f88: addi s6,s6,2
10ce: sh   a0,130(s0)  ; V->W        f8a: sh   a0,130(s0)      ; checkpoint written
10d2: sh   s6,132(s0)  ; V->IP       f8e: sh   s6,132(s0)
10d6: j    626                      f92: j    66e
```

Only case bodies were replaced. A variant that keeps `w`/`ip` in registers and writes them only at switch
time was **not** attempted — it would be smaller and it is not a candidate.

## 7. Tests — new file, and two mutation tests

The suite covered `+ - *` (8 of the 10 words were untested; a kernel that computed `AND` as `OR` would have
passed everything). New: `tests/binops.fs` + `tests/binops.expected` (32 assertions: all ten ops, signed vs
unsigned compare, the `& 31` shift mask, 32-bit wraparound, the words from inside colon definitions, and a
net-stack-effect check). `tests/run.sh` builds a third binary `artifacts/host_binops` with
`-DP54_BINOPS=10` and routes `binops*.fs` to it, exactly as `blocks*.fs` already routes to `host_blk`.

The binops file was also run against **every rung** (1, 2, 3, 5, 6, 8, 9, 10) and both mechanisms, plus the
unmodified base build: identical transcript in all 12 runs, and the dictionary stayed at 64 words in each.

**Mutation tests** (break it, watch the test fail, restore — the restore was verified byte-identical against
the pre-mutation artifacts, then regenerated with `tools/p54_gen.py`):

| mutant | what it breaks | result |
| --- | --- | --- |
| **M1** `p54_binops[cf - P_ADD](b, TOS)` | operands swapped in the kernel | **caught**: the transcript collapses (`.` itself is built on `-`, `<`), run ends `ERR_STACK` at line 32 |
| **M2** `[5] = p54_op_XOR` | table slot 5 (`AND`) dispatches `XOR` | **caught, minimally**: `12 10 AND .` prints `6` instead of `8`, and only the two AND lines differ — `5-2-22…-1206-114-16…` vs `…-1208-0-14-…` |
| **M3** `p54_binops[cf - P_ADD + 1]` | slot indexed one off (the exact failure the `_Static_assert`s guard against) | **caught**: transcript becomes `ERR_STACK` only |

M1/M3 show a property worth knowing: `.` is built on `+ - < /MOD 0=`, so most mutations to those ops destroy
the printer and the golden transcript becomes an empty/garbage run — still a failure, but M2 is the sharper
oracle because it changes exactly two values. `artifacts/host_m1..host_m3` and `artifacts/m*.out` are the
evidence; all three mutants were reverted and the suite re-run green.

## 8. Two real bugs found while building this (both would have shipped silently)

1. **`-DP31_SUBSET` drops `DOCOL/DOVAR/DOCON`.** `p31_cases.inc` gates those three cases on `P_HAVE_DOCOL`
   etc., but they are *not* `X(...)` entries in `p31_prims.inc`, so a generated subset list misses them.
   The build still links, `.text` is 12 B **smaller** (a fake win), and every colon word answers `?`.
2. **`P_HAVE_*` gates the dictionary header too.** `p31_prims.inc` has the same
   `#if !defined(P31_SUBSET) || defined(P_HAVE_ADD)` wrapper as the case bodies, so removing a *case* also
   removed the *header*: `-DP54_BINOPS=10` built fine, `.text` was 4 B smaller again, and the dictionary had
   **54 of 64 words** (`1 2 OR .` → `OR?`). Fixed by a second generated file, `src/p54_headers.inc`, that
   re-enables the header halves between `vm_enter()` and `boot_init()`. Both bugs are why `tests/binops.fs`
   exists and why the generated subset list refuses to emit over an id it cannot place.

`fp10` was re-measured after the fix; the ELF numbers are unchanged (the ULP build is `-DIMAGE`, so
`boot_init()` is not compiled into the image at all) — the bug was a *host/bake* bug, not a size bug, and it
would have baked a 54-word dictionary.

Unrelated, pre-existing, found while writing the test: the prelude's `.` cannot print INT_MIN
(`2147483647 1 + .` prints `-./,),(` on the **base** build too — `.` negates first and `-2147483648` stays
negative, so the digit loop divides a negative). Not touched by P54; the test wraps via `-` instead.

## 9. Projected total at full conversion — **ESTIMATE**

Measured anchors: in-kernel shared machinery 46–66 B (§3), one leaf 4–10 B, one table slot 4 B, per-body
sizes from §2. Applying them to the four *near*-shape bodies that remain:

| extension | bodies removed | new kernel + leaves | Δ`.text` | Δ`.rodata` | ESTIMATE net pool |
| --- | --- | --- | --- | --- | --- |
| unary group (`INVERT` 22, `0=` 24) — `top = f(top)` | 46 | 46…66 kernel + 8 leaves = 54…74 | **+8 … +28 (a loss)** | +8 | **+16 … +36** |
| two-result group (`/MOD` 38, `U/MOD` 48) — `f(a,b,&q,&r)` | 86 | 46…66 kernel + 16 leaves = 62…82 | **−24 … −4** | +8 | **−16 … +4** |
| **all 14 shareable words** (10 measured + these two ESTIMATED) | 530 | 118 + 54…74 + 62…82 | −280 … −240 | +72 | **−208 … −168 — worse than the 10-word rung** |

So the curve has already flattened and turned: 10 words buy **−224 B of pool**, and adding the four
near-shape words would move it to **−168 … −208 B**, i.e. *backwards*, because a second and third kernel
each pay their own 46–66 B of shared machinery plus their own table. **Not recommended.** The task's
projected "~450–590 B of bodies → −300 … −470 B" needs 15–20 same-shape words; there are 10, and 398 B of
them produce −224 B of pool.

## 10. Verdict

**Ship it as `-DP54_BINOPS=10`, at −224 B of pool (= +224 B of application space after a re-bake).**

Ranked, all measured, all suite-green:

1. **`-DP54_BINOPS=10`** — `.text` −280, `.rodata` +56, **pool −224**, whole dictionary unchanged.
   Ship steps: add `-DP54_BINOPS=10` to the **ULP C flags** (IDF's toolchain file, not a per-file
   `#define`); raise `MEMSZ` 1 400 → **1 624** in `src/ulp_repl.c` and re-bake with `tools/bake.sh 1624`
   (**ESTIMATE of the consequence, arithmetic on the measured −224**: app space 354 → 578 B,
   `BLKADR` 1 272 → 1 496). The bake flag set does *not* need the P54 flag — the dumped `mem[]` is
   byte-identical with and without it (sha `16a495b2…` both ways) — but if it is added there it must be
   added everywhere.
2. `-DP54_BINOPS=10 -DP54_OPSW` — pool −222, i.e. 2 B worse, same instruction count. Only interesting if a
   future P50-style assembly kernel wants to avoid indirect calls.
3. `-DP54_BINOPS=5` — pool −74. Worth it alone if only the five most common ops are wanted (that is the
   natural half-way rung; note 5 → 10 is worth another −150).
4. **Do not** ship holes-as-NULL (−14 B more, silent wrong dispatch), and **do not** extend to the unary /
   two-result groups (§9: the 14-word total lands *backwards*, at −168 … −208 B of pool).

What it costs, plainly: +56 B of `.rodata`, ~+8 instructions per converted dispatch (cycles are board-only
and were not measured), one generated table with four named holes, and a two-site preprocessor gate whose
failure mode is a silently smaller dictionary — which is why the suite now builds a P54 binary and types all
ten words.

## 11. Exact diff of the winner

`winner.diff` in this directory (883 lines) is the complete, exact diff: `src/uforth.c` and
`src/p33_cases.inc` against the untouched `probe/repl/src/`, plus every new file (`tools/p54_gen.py`,
`src/p54_ops.h`, `src/p54_cases.inc`, `src/p54_subset.inc`, `src/p54_headers.inc`, `tests/binops.fs`,
`tests/binops.expected`, `tests/run.sh`). The four `src/p54_*` files and the case labels are **generated**
from the one op list in `tools/p54_gen.py`; regenerate with `python3 tools/p54_gen.py` (deterministic: it
reproduced the pre-mutation files byte for byte after the mutation tests).

The two hand-edited hunks are:

```diff
--- probe/repl/src/uforth.c
+++ P54-ops/src/uforth.c
@@ -409,6 +409,21 @@
 _Static_assert(SD == 16, "dispatch.S assumes SD=16 for the stack wrap check");
 _Static_assert(sizeof(VM) == 136, "dispatch.S hard-codes the VM layout");
+
+/* ---- P54: the same-shape binary primitives, driven from one table ----  (see file for the GUARDRAILs) */
+#if defined(P54_BINOPS)
+#include "p54_subset.inc"
+#include "p54_ops.h"
+#endif
@@ -823,6 +838,15 @@
     }
 }
+
+#if defined(P54_BINOPS)
+/* second half of the subset gate: re-enable the ten dictionary HEADERS before boot_init() */
+#include "p54_headers.inc"
+#endif
```

```diff
--- probe/repl/src/p33_cases.inc
+++ P54-ops/src/p33_cases.inc
@@
+#if defined(P54_BINOPS)
+/* labels + the one shared body for ADD…ULT, inside vm_enter()'s switch */
+#include "p54_cases.inc"
+#endif
+
 #if defined(P43_TASKS)
```

and the whole mechanism the winner compiles to (`src/p54_cases.inc`, non-`OPSW` arm):

```c
#if P54_BINOPS >= 1
        case P_ADD:   /* P54 op 1, slot 0 */
#endif
… one `case P_<id>:` per converted rank, gated by the same `#if` …
#if P54_BINOPS >= 1
        {
            b = POP();
            TOS = p54_binops[cf - P_ADD](TOS, b);
            break;
        }
#endif
```

with `src/p54_ops.h` holding the leaves and the table:

```c
static u32 p54_op_ADD(u32 a, u32 b) { return (a + b); }      /* 4 B */
…
static u32 p54_op_unreachable(u32 a, u32 b) { (void)a; (void)b; pl_halt(0x54u); return 0u; }
_Static_assert(P_AND == P_ADD + 5, "P54 slot drift: AND");   /* one per op, against the real primitive enum */
static const p54_binop_t p54_binops[P54_NSLOT] = { [0] = p54_op_ADD, … [3] = p54_op_unreachable, … };
```

## 12. What I could not measure, and the proposals I did not build

* **Cycles.** Host-only work; no board, no flash. Only the instruction counts in §5 and the (unchanged)
  DISP are measured; the +15 % figure in §5 is a *reading of those counts*, not a timing.
* **App space after the change.** The −224 B pool delta is measured; the 354 → 578 B app space is
  arithmetic on it that only a real `tools/bake.sh 1624` + `ulp_repl.c` `MEMSZ 1624` can confirm.
* **A `u16` pointer table** (proposal, unmeasured): all ten leaves live below `0x0216`, so a 14×2 B table
  would save **28 B** more of `.rodata`. It relies on function addresses staying under 64 KB and on an
  implementation-defined pointer round-trip through `u16`; at 28 B it is not worth the class of bug it
  invites. Do not ship it without a linker assert on `.text` size.
* **Shrinking the four holes** by re-using `INVERT`/`0=`'s ids as a second unary kernel — §9 says ≈ 0 B.
* **A dispatch that keeps `w`/`ip` in registers** (would be smaller, drops the P27 save point) — explicitly
  out of scope, per TASK step 4.
