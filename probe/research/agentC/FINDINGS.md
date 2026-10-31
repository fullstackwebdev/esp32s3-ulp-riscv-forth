# agentC — the real data-stack high-water mark, and what SD must be

| | |
| --- | --- |
| Runs on | **host only** (no board, no serial device touched) |
| Question | What is the deepest the Forth stacks actually go, and is `#define SD 16` a sizing choice or a bug? |
| Answer | **Peak 17 data cells / 15 return cells on a *modest* workload — `SD 16` is already a correctness bug.** `15 FIB .` prints `610` at SD 256 and **`377` at SD 16**. Recommend **SD 32**. |
| Cost of the recommendation | **+394 B of pool** (+384 `.bss` measured on the rv32 twin build: `vm_live` +128, `tsk[2]` +256; +10 text/rodata). Pool is 7 680/7 856, so SD 32 is **218 B over** and has to be paid for. |
| Time | ~40 min |

Working copy: `probe/research/agentC/` (the shipping `probe/repl/src/` was **not** edited). Every
number below comes from `src/uforth.c` of that copy, which is `probe/repl/src/uforth.c` plus the
instrument and one host-only task step.

---

## 1. The instrument

`src/uforth.c:319` — two exported globals, `u32 hw_max_sp, hw_max_rsp;`.

They are updated **where the pointer increments**, not sampled between dispatches:

```c
src/uforth.c:320  static void PUSH(u32 v) { ds[sp & (SD - 1)] = v; sp++; if (sp > hw_max_sp) hw_max_sp = sp; }
src/uforth.c:324  static void RPUSH(u32 v) { rs[rsp & (SD - 1)] = v; rsp++; if (rsp > hw_max_rsp) hw_max_rsp = rsp; }
```

`PUSH`/`RPUSH` are the *only* two places that raise `sp`/`rsp` — `DROP` is `sp--`
(`p31_cases.inc:56`), `(LOOP)`/`UNLOOP` are `rsp -= 2` (`p31_cases.inc:35,46`) — so both increments and
nothing else are covered, including the literals `interpret()` pushes outside `run()`
(`uforth.c:715,719` in the original). Sampling at the switch would have been wrong in the one way that
matters: `ds[sp & (SD-1)]` masks the *index*, so at SD 16 a program that pushes 17 cells keeps counting
`sp` while overwriting slot 0 — every sampled depth looks legal.

Read at exit, on **stderr** (`src/uforth.c:892`, called from `:916` and `:964`):
`HWM sp=17 rsp=15 (SD=32, sizeof(VM)=264, NTSK=3)`. stderr because stdout of `tests/suite.fs` is diffed
against `tests/expected.txt` — an instrument that pollutes the golden output gets the golden file
regenerated, and then the suite tests nothing.

One host-only driver was needed (`src/uforth.c:874`): the chip steps tasks once per wake from
`ulp_repl.c:331`, the host has no wake loop, so without a step after each loaded line `SPAWN` creates
tasks that never execute and row (c) would have reported the *outer* interpreter's depth. It refuses on
a dirty stack exactly as `ulp_repl.c:322` does.

The `SD == 16` / `sizeof(VM) == 136` pins (`uforth.c:347,348`) are gated to `#if SD == 16` and the layout
is asserted at every SD as a formula (`src/uforth.c:364`: `sizeof(VM) == 8 * (SD + 1)`), so the probe can
vary SD without deleting the assert that protects the shipping build.

**Measurement build: `-DSD=256`.** With a 256-cell stack the peak cannot be capped and no value is
aliased. This is the row that is believed; the SD-16 build is the *control*.

---

## 2. Measured peaks

`-Os -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=1704 -DSD=256 -DNTSK=3`,
`src/p39_prelude.fs` loaded first in every run (so the compiler path is inside every row).

| Workload | max **data** cells | max **return** cells | output (proof it ran) |
| --- | --- | --- | --- |
| (a) `tests/suite.fs` (prelude + 29 lines) | **6** | **7** | `5442615-…-1` = `tests/expected.txt`, byte for byte |
| (b) `: FIB … ; 15 FIB .` | **17** | **15** | `610` |
| (c) `TA/TB/TC` + `PAUSE`, 3 `SPAWN` | **3** | **3** | `135246` |
| (d) `1 2 … 10 + + + + + + + + + .` | **10** | **3** | `55` |
| **peak over the four** | **17** | **15** | |
| extra: `16 FIB .` | 18 | 16 | 987 |
| extra: `18 FIB .` | **20** | 18 | 2584 |
| extra: `20 FIB .` | 22 | 20 | 6765 |
| extra: `24 FIB .` | 26 | 24 | 46368 |

The four extra rows are not padding: they show the rule that sizing has to be based on.

> **Data-stack depth = user recursion depth + 2. Return-stack depth = user recursion depth.**

Three independent points fit it exactly (15→17/15, 20→22/20, 24→26/24), which is also the instrument's
own sanity check: a counter that was off by one would not land on `n+2` three times
(`docs/14-probe-rules.md` R9).

Row (a) is why this was never noticed: **every regression test in the suite peaks at 6 cells.** The
suite cannot see this bug, and no amount of passing it will change that.

`P13` (`docs/probes/P13-stack-depth.md`) recorded "peak 20 data + 7 return". Both halves are confirmed
here: the suite's return peak is exactly **7**, and a merely-18-deep recursion reaches exactly **20**
(`18 FIB`). P13's figure was right; `SD 16` has been too small ever since.

---

## 3. SD 16 is a bug, not a tight fit — the proof

Same source, same flags, only `-DSD` differs:

```
$ out/hwm256_sd256_ntsk3 src/p39_prelude.fs work/w_fib.fs     # SD 256
HWM sp=17 rsp=15 (SD=256, sizeof(VM)=2056, NTSK=3)
610

$ out/literal_sd16 src/p39_prelude.fs work/w_fib.fs           # SD 16, NTSK 2 = the shipping dial
HWM sp=17 rsp=15 (SD=16, sizeof(VM)=136, NTSK=2)
377
```

`15 FIB .` must print **610**. At the shipping `SD 16` it prints **377**. The 17th push writes
`ds[16 & 15] = ds[0]`, which is the cell the outermost frame parked its `n` in, and the recursion adds
the wrong pair of values. `16 FIB .` gives `377` where 987 is correct. Return-stack depth 16
(`16 FIB`, rsp=16) clobbers `rs[0]` the same way.

So at SD 16 the machine supports **recursion depth ≈ 13**, silently, with a wrong answer instead of an
error. That is not a budget line; it is a wrong-answer bug that ships as a passing test suite — the
pristine `probe/repl/src/uforth.c` is **green** on `tests/suite.fs` (output matches `tests/expected.txt`
byte for byte) while `15 FIB .` on that same binary answers wrongly.

---

## 4. What each SD step actually costs (rv32 twin build)

Compiled with the ULP baseline flags read out of IDF's own toolchain file —
`-Os -march=rv32imc_zicsr_zifencei -mdiv -fdata-sections -ffunction-sections -msave-restore` — i.e. the
real target ABI, not the host:

| SD | `sizeof(VM)` | `.bss vm_live` | `.bss tsk[NTSK=2]` | engine bss (vm_live+tsk) | **Δ pool vs SD 16** | text+rodata |
| --- | --- | --- | --- | --- | --- | --- |
| 8 | 72 | 72 | 152 | 224 | **−192** | 5 215 |
| **16** | **136** | **136** | **280** | **416** | **0** | 5 223 |
| 32 | 264 | 264 | 536 | 800 | **+384** (+10 text/rodata = **+394**) | 5 233 |

Harness check (`docs/14-probe-rules.md` R9): the shipping ELF agrees with the twin build symbol for
symbol — `riscv32-esp-elf-nm -S build/esp-idf/main/ulp_main/ulp_main.elf` gives `vm_live 0x88 = 136` and
`tsk 0x118 = 280`, exactly the SD-16 row. Pool from the same ELF: text 4 764 + rodata 372 + data 1 720 +
bss 824 + 16 pad = **7 680 / 7 856**, which is `countdown.sh`'s own figure and leaves **176 B spare**.

NTSK is the other dial (measured at SD 32): `NTSK 2→1` is **−268 B bss, −108 B text = −376 B**.

---

## 5. Decision — three numbers

1. **Measured peak: 17 data / 15 return cells** (and 20/18 for an 18-deep recursion — P13 never was
   wrong).
2. **Safety margin to ship: +15 cells, i.e. 1.88× the measured peak**, and it is stated as a capability
   rather than a cell count: *the machine must run recursion to depth 30*. Half a step below, SD 16 tops
   out at depth 13 — the machine's most common use (a recursive word) dies at the 14th level, silently.
3. **Resulting SD: 32** — the next power of two (`uforth.c:37`, mask at `:311,315`), which buys depth 30.
   **Pool cost: +394 B** (`.bss` +384, text/rodata +10).

**SD 16 must be raised even though it costs bytes.** This is a correctness bug: `15 FIB .` returns a
wrong answer on the current engine, and nothing in `tests/` can detect it because the suite peaks at 6.

Where the 218 B comes from (pool 7 680 + 394 = 8 074 vs 7 856):

| way to pay | bytes | what it costs in capability |
| --- | --- | --- |
| `MEMSZ` 1 704 → 1 486 | −218 | app space 810 → **592 B** (re-bake `image.h` at the new `MEMSZ`); `countdown.sh` goes from 52 B short to ~446 B short |
| `NTSK` 2 → 1 at SD 32 | −376 | **loses the second task slot** — R4's measured interleave (`135246`) needs ≥ 2 |
| both, `MEMSZ` → 1 704 | −168 net | a 2-task machine with SD 32 and nothing else |

Recommendation: **SD 32 + `NTSK` 2 + `MEMSZ` 1 486**, and record in `countdown.sh` that the block layer
now needs another ~394 B of pool. The alternative — keep SD 16, recursion depth 13, and turn the silent
wrap into a named error — is a band-aid: it converts a wrong answer into a refusal without making the
machine able to run a 14-deep recursion, and it still fails the only workload that found this.

### Knock-on edits SD 32 requires (all of them, or the build lies)

| file:line | what pins SD 16 |
| --- | --- |
| `probe/repl/src/ulp_repl.c:31`, `probe/repl/src/ulp_p39.c:20` | `#define SD 16` in the shipping images |
| `probe/repl/src/uforth.c:347` | `_Static_assert(SD == 16, "dispatch.S assumes SD=16 …")` |
| `probe/repl/src/uforth.c:348` | `_Static_assert(sizeof(VM) == 136, …)` |
| `probe/lev/p50asm/dispatch.S:35,45,53,74` | `andi t6, s3, 15` — the wrap mask baked into the asm dispatcher |
| `probe/repl/src/ulp_repl.c:31` comment | `/* P13: peak 108 B */` — P13's own number is >16 cells |

The two `_Static_assert`s are the reason this cannot be a quiet `-D`: a shipping build at SD 32 fails to
compile today, which is the correct behaviour and should be kept.

---

## 6. What this does *not* answer

* **Board-only:** nothing here was run on the chip; the `.bss`/text figures are a twin cross-compile of
  the same source at the same flags, cross-checked against the shipping ELF's symbols.
* The **outer-interpreter error path** (`uforth.c:723` `sp = rsp = 0` after `errf`) and the interactive
  REPL path were not instrumented separately; every row above goes through `load()`.
* **`WORD`/`FIND`/`number`** are C, not stack users, so they cannot deepen the Forth stacks — but the
  *deepest single prelude word* was not measured word by word the way P13 asked (row (a) bounds the sum
  at 6, which makes it moot).
* Row (c) needed `-DNTSK=3`: at the shipping `NTSK 2` the third `SPAWN` is refused by name
  (`ERR_TASKS`, `uforth.c:636`) — expected, and `tests/ntsk.fs` asserts it.

## 7. Reproduce

```bash
cd probe/research/agentC
timeout 300 bash run.sh                       # all four rows at SD 256, the SD-16 control, and the three sizings
timeout 300 gcc -Os -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=1704 \
    -o out/literal_sd16 src/uforth.c          # the exact command from the task, unchanged
timeout 300 out/literal_sd16 src/p39_prelude.fs work/w_fib.fs     # HWM sp=17 … / 377   <- the bug
timeout 300 out/hwm256_sd256_ntsk3 src/p39_prelude.fs work/w_fib.fs  # HWM sp=17 … / 610  <- the truth
```

Logs for every row are in `out/*.log`; the rv32 twins are `out/ulp_sd{8,16,32}.o` and
`out/o_sd{32,16}_ntsk{1,2}.o`.
