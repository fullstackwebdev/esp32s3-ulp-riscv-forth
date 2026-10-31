# P52 — dispatch and accessor levers on the ULP engine: measured, in bytes

Engine: `probe/research/agentA/src/ulp_repl.c` + `uforth.c` (copied, never edited in place), built with the
exact command IDF recorded and the exact link line from the shipping build. Board untouched.

## Method, and the proof that the twin is the shipping machine

`tools/disasm.sh`'s method, adapted into `measure.sh` (one variant per invocation) + `sweep.sh` /
`runall.sh` (the matrix). Everything lands in `agentA/out/`.

```
cd /home/user/research/esp32-rv32/probe/research/agentA
./measure.sh base                      # re-measures the baseline every run
./runall.sh                            # every row in this document, appended to RESULTS.txt
./verify.sh cgoto_fold -DVM_CGOTO -DUC_ACCESS -DUC_FOLD   # host suite + ntsk + wild
```

Validation before any number was believed:

* `out/base.text` sha256 `3697ed4e58faad61…` == `.text` of the **shipping** `build/esp-idf/main/ulp_main/ulp_main.elf`
  (`out/ship.text`). The twin reproduces the flashed code byte for byte, so a delta from `base` is a delta in the
  real binary.
* Baseline: `.text` **4764** B, `.rodata` **372** B, `.data` 1720 B, `.bss` 824 B (whole ULP image).
  `vm_enter` = 2524 B, 883 instructions.
* Two rows that must differ (below: `-fno-jump-tables`, `-fno-omit-frame-pointer`) do differ, and rows that must be
  identical keep the same sha — the harness is not measuring the same program twice.

Host check per shape (`verify.sh`, `-Os -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=1704`):
`tests/suite.fs` vs `tests/expected.txt`, `tests/ntsk.fs` (must abort on the third SPAWN), and the new
`tests/wild.fs` (wild-address reads/writes, added here).

## Table — variant → Δ.text → Δ.rodata → suite

| variant | flags | .text | Δ.text | .rodata | Δ.rodata | host |
|---|---|---|---|---|---|---|
| **base** | — | 4764 | 0 | 372 | 0 | PASS |
| `cgoto` (TASK 1) | `-DVM_CGOTO` | 4758 | **−6** | 372 | **0** | PASS |
| `uc` (TASK 2 as asked) | `-DUC_ACCESS` | 4804 | **+40** | 372 | 0 | PASS |
| `cgoto_uc` | `-DVM_CGOTO -DUC_ACCESS` | 4794 | +36 | 372 | 0 | PASS |
| `fold` (TASK 2 folded) | `-DUC_ACCESS -DUC_FOLD` | 4750 | **−14** | 372 | 0 | PASS |
| **`cgoto_fold`** (best safe) | `-DVM_CGOTO -DUC_ACCESS -DUC_FOLD` | **4742** | **−22** | 372 | 0 | PASS |
| `cgoto_uc_ni` | `-DVM_CGOTO -DUC_ACCESS -DUC_NOINLINE` | 4798 | +40 | 372 | 0 | — |
| `cgoto_fold_f` | + `-DUC_FETCH` | 4754 | −10 | 372 | 0 | PASS |
| `cgoto_ucstack` (unsafe half) | `-DVM_CGOTO -DUC_ACCESS -DUC_STACK` | 4806 | +48 | 372 | 0 | — |
| `cgoto_ucall` (**unsafe**, refuted below) | `-DVM_CGOTO -DUC_ACCESS -DUC_ALL` | 4706 | −58 | 372 | 0 | — |
| `cgoto_ucall_fold` (**unsafe**) | + `-DUC_FOLD` | 4704 | −60 | 372 | 0 | — |
| `-mrelax` (compile) | | 4764 | 0 | 372 | 0 | — |
| `-mrelax` + `-Wl,--relax` (link) | | 4764 | 0 | 372 | 0 | — |
| `-fno-jump-tables` | | 5120 | **+356** | 104 | **−268** | — |
| `-ftree-switch-conversion` | | 4764 | 0 | 372 | 0 | — |
| `-fno-tree-switch-conversion` | | 4764 | 0 | 372 | 0 | — |
| `-mcmodel=medlow` (default) | | 4764 | 0 | 372 | 0 | — |
| `-mcmodel=medany` | | — | **LINK FAILS** | — | — | — |
| `-fira-region=all` | | 4764 | 0 (code differs) | 372 | 0 | — |
| `-falign-functions=1` | | 4764 | 0 | 372 | 0 | — |
| `-falign-functions=2 -falign-jumps=2 -falign-loops=2` | | 4764 | 0 | 372 | 0 | — |
| `-fomit-frame-pointer` (default at -Os) | | 4764 | 0 | 372 | 0 | — |
| `-fno-omit-frame-pointer` | | 5140 | **+376** | 372 | 0 | — |
| `-Oz` (vs the shipping `-Os`) | | 4764 | **0, byte-identical** | 372 | 0 | — |
| `-mno-save-restore` | | 4764 | 0 | 372 | 0 | — |
| `-fno-crossjumping` | | 5150 | +386 | 372 | 0 | — |
| `-fno-ipa-icf` | | 4786 | +22 | 372 | 0 | — |
| `-fira-algorithm=priority` | | 4788 | +24 | 372 | 0 | — |
| `-fno-inline` | | 4772 | +8 | 372 | 0 | — |
| `-finline-functions`, `-fmerge-all-constants`, `-fconserve-stack` | | 4764 | 0 | 372 | 0 | — |
| `-Wl,--icf=all` | | — | **LINK FAILS** (GNU ld has no `--icf`; lld only) | — | — | — |

Same levers on the winning shape: `-mrelax` 0, `-fno-jump-tables` 0 (the table is ours now, so the flag has
nothing to remove), `-Oz` 0, `-fira-region=all` 0 bytes (different code), `-fno-omit-frame-pointer` +448,
`-fno-crossjumping` +352. No lever adds to `cgoto_fold`.

## TASK 1 — computed goto: −6 B of .text, and the 268-byte table is **conserved, not removed**

The premise in the task ("ids 0..62, 63-entry table") undercounts this build: with `P43_TASKS` the switch covers
ids 0..66, i.e. **67** slots. Measured, both tables are **67 × 4 = 268 B**:

* before: compiler-generated jump table inside `.rodata`, first entry at `0x1304`, range-tested with
  `li s3,66; bltu s3,a0 → default`.
* after: `vm_cgoto_tab.0`, a `static const void *const` **inside `vm_enter`**, 268 B (symbol size `0x10c`) at
  `.rodata 0x1300`.

`.rodata` therefore does not move at all (372 → 372): the switch's table and the label table are the same
object — absolute 4-byte addresses indexed by `cf`. What changed is only where the range test sits and which
side the error path is on:

```
base  : bltu 66,a0 -> default ; slli ; addi tbl ; add ; lw ; jr        (6 instr, 883 instr in vm_enter)
cgoto : bgeu 66,a0 -> err    ; addi tbl ; slli ; add ; lw ; jr         (6 instr, 879 instr in vm_enter)
```

So the dispatch itself is a wash (−4 instructions in the function, `vm_enter` 2524 → 2518 B, image −6 B) and the
table cannot be shrunk in C: `&&label` is a 4-byte absolute address. A 2-byte offset table is only reachable from
assembly (P50's territory) and would be −134 B of `.rodata` if built; that is a proposal, not a measurement.

Changes: `src/uforth.c:744-770` (table), `:776-806` (fetch/label/table/index with the range test kept),
`:820-838` (one `vm_tail` for both shapes), `src/p33_cases_cg.inc` (generated by `tools/gen_cg.py` from
`p31_cases.inc` + the `p33_cases.inc` tail: `case P_X:` → `vm_c_P_X:`, `break;` → `goto vm_tail;`,
`continue;` → `goto vm_fetch;`).

## TASK 2 — unchecked accessors: the stated shape **fails (+40 B)**; the folded shape wins (−22 B)

First, the premise needs one correction, and it is the reason the aggressive variant is unsafe: addresses do
**not** all come from the machine. `@ ! c@ c! w@ w! TYPE` take an address off the **data stack** — that is a
pointer the Forth program chose, and `P()`'s `&junk` fallback exists precisely so a wild one is harmless. Only
`V_*` (offsets into `mem[]`), `PAD`, the dictionary cursor and token addresses (`w`, `ip`) are in range by
construction. `tools/gen_uc.py` therefore converts the 13 body lines whose operand is none of `TOS`/`POP()`
(`src/p33_cases_uc.inc`) and leaves the seven stack-operand bodies checked.

Results:

* safe subset, accessors beside the checked ones: **+40 B** (`uc`) / **+36 B** (`cgoto_uc`). Not a check cost:
  the unchecked accessors become *additional* out-of-line functions (`rd32u`, `wr16u`, `wr32u`, `wr8u` appear in
  the symbol table) instead of being shared with the checked callers, and GCC then also outlines `PUSH` (+30 B)
  and `wr32u` (+42 B). Forcing them `noinline` (`-DUC_NOINLINE`) does not recover it (+40 B at 4798).
* the decomposition proves the number belongs to the inliner, not to the check: converting *only* the
  stack-operand lines is **+48 B**, converting *both* sets is **−58 B**. Two disjoint halves of one edit costing
  +36 and +48 while their union wins 52 is not a property of a `cmp`; it is an inlining-threshold flip.
* **UC_FOLD** (`src/uforth.c:131-149`) is the shape that actually pays: the unchecked core is the only copy of
  each load/store, and the checked accessors become "test + call the core" (`rd8/rd16/wr8/…` keep their exact
  semantics: out-of-range → `junk`/`0`). The check stays where the program's own pointers arrive and the dispatch
  bodies go straight to the core. Where it lands: `vm_enter` 2524 → **2442 B** (−82), `wr32u` appears as one
  out-of-line leaf (+40) instead of a second accessor family, table 268 B, and the checked `rd8/rd16/rd32/wr8/
  wr16/wr32` stay single copies. **−14 B** alone, **−22 B** with computed goto. `tests/wild.fs` pins the
  semantics: wild `! @ c@ c!` at 100000 and at `-1`-as-byte still answer 0 and leave the dictionary intact, and
  every shape prints the same bytes.
* `-DUC_FETCH` (also unchecked `rd16_paged(w)` / `rd16_paged(ip)` in the loop) **loses 12 B** against
  `cgoto_fold` (4754 vs 4742) — the two hot loads are cheaper as calls to the shared `rd16` than inlined.

## Recommendation, ranked by measured bytes (all safe, all suite-green)

1. **`-DVM_CGOTO -DUC_ACCESS -DUC_FOLD` → −22 B** (`.text` 4764 → 4742, `.rodata` unchanged). 22 B of pool text;
   `MEMSZ`/app-space arithmetic in `src/ulp_repl.c:24-31` must be recomputed if it ships, and the flags belong in
   the ULP C flags, not in a per-file `#define` (the ULP sub-build takes them from IDF's toolchain file).
2. `-DUC_ACCESS -DUC_FOLD` alone → −14 B, if the dispatch rewrite is not wanted.
3. `-DVM_CGOTO` alone → −6 B. Only worth it if the computed-goto shape is wanted for P50's asm work; as a byte
   lever it is noise.
4. Do **not** take `-DUC_ALL` (−58 B): it converts `@ ! c@ c! w@ w! TYPE` to unchecked, so `100000 !` writes
   past `mem[]`. Cheaper by 36 B than the recommendation and not shippable.

## What failed, and by how much

* Unchecked accessors in the requested shape: **+40 B**. Cheaper to keep the check shared.
* `-fno-jump-tables`: **+356 B text / −268 B rodata** (net +88). The table is load-bearing.
* `-fno-omit-frame-pointer`: +376 B. `-fno-crossjumping`: +386 B. `-fno-ipa-icf`: +22 B.
  `-fira-algorithm=priority`: +24 B. `-fno-inline`: +8 B.
* `-mcmodel=medany`: does not link — `address 0x2150 of … section .bss is not within region 'ram'`; GOT-relative
  addressing pushes `.bss` past the ULP ld script's window.
* `-Wl,--icf=all`: `ld: unrecognized option` (GNU ld; needs lld).
* Zeroes, exactly: `-mrelax` (with and without `-Wl,--relax`), `-ftree-switch-conversion`,
  `-fno-tree-switch-conversion`, `-mcmodel=medlow`, `-falign-functions=1`, `-falign-functions=2/…`,
  `-fomit-frame-pointer`, `-mno-save-restore`, `-finline-functions`, `-fmerge-all-constants`,
  `-fconserve-stack`, and **`-Oz` is byte-identical to the shipping `-Os`** on this file under GCC 14.2 — the
  obvious "just build smaller" lever is already spent.

## Residual risks

1. **Latent bug found, not fixed:** `probe/repl/src/uforth.c:77` (`agentA/src/uforth.c:82`) —
   `rd16(a) = a + 1u < MEMSZ ? … : 0`. For `a = 0xFFFFFFFF` the addition wraps to 0, the test **passes**, and the
   load runs at `mem - 1`. On the host `-1 @` segfaults; on the ULP it silently reads the byte below `mem[]`
   instead of answering 0. Fix is one instruction: test `a < MEMSZ - 1`. It is a change to the shipping reader,
   so it is reported here, not made (`tests/wild.fs` documents why the row is absent).
2. Cycle cost is **not** measured — R8: timing is board-only, and these are all `.text`/`.rodata` numbers.
   Computed goto is traditionally a *speed* lever; nothing here proves or disproves a cycle win.
3. The TASK 2 byte numbers are inliner-dependent (−58 for the union of two halves that cost +36 and +48 alone).
   The recommendation (−22 B) is a whole-image delta with the suite green, not a model.
4. The `err()` path for a token `>= P_COUNT` is preserved by an explicit `cf >= P_COUNT` test, but no host test
   constructs such a token; it is verified by reading the code and by the `default: err(); break;` parity, not by
   a test row.
5. `out/`, `RESULTS.txt` and the generated `.inc` files are the evidence; `tools/gen_cg.py` and
   `tools/gen_uc.py` regenerate them deterministically (both refuse to emit on a shape they do not recognise).
