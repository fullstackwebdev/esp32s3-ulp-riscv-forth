# P21 — How much C stack does the engine actually use?

| | |
| --- | --- |
| Runs on | **host only** — `-fstack-usage` + `objdump -dr`, no board, no `/dev/ttyACM*` opened |
| Time box | 15 min, one run — **overran** (see §2.5); nothing was re-run for a better number |
| Verdict | **PASS** — the deepest static chain is **176 B**; with the interrupt save on top the worst case is **244 B**. The 400 B line in §4.3 is not too small, it is **156 B too large**: **320 B** is the recommendation, returning **80 B** to the dictionary |

Files written (all inside `probe/results/P21-c-stack/`; `docs/` and `probe/uforth/` untouched):

| File | What it is |
| --- | --- |
| `uforth.c`, `ulp_stubs.c` | verbatim copies of P12's engine tree |
| `ulp_engine.o`, `ulp_engine.su`, `ulp_engine.dis` | the engine built with the **exact P12 ULP flags** + `-fstack-usage`; `.dis` is `objdump -dr` |
| `uforth.su`, `ulp_stub_only.su` | engine-TU-alone and control-image `.su`, for the "is the frame the same if main moves" cross-check |
| `chain.py` | call graph from `R_RISCV_CALL*` relocations → max-sum chain from `main` |
| `host_probe.c`, `host_probe`, `host_probe.su`, `host_probe.dis`, `host_probe.log` | the runtime cross-check: host build with `-finstrument-functions` |
| `ulp_riscv_interrupt.o`, `ulp_riscv_gpio.o`, `irq_cflags.sh` | attempt to size the IDF interrupt *handler* (came out empty — §2.4) |
| `boot_min.fs` | copy, loaded by the host probe |

Build (exactly what was executed, every command under `timeout 30`):

```sh
export IDF_PATH=/home/user/research/esp32/esp-idf && . $IDF_PATH/export.sh
riscv32-esp-elf-gcc -DIS_ULP_COCPU -DULP_RISCV_REGISTER_OPS -Os -march=rv32imc_zicsr_zifencei -mdiv \
    -fdata-sections -ffunction-sections -fstack-usage -c ulp_stubs.c -o ulp_engine.o
riscv32-esp-elf-objdump -dr ulp_engine.o > ulp_engine.dis
python3 chain.py main                       # 176 B, path in §1.2
gcc -Os -no-pie -finstrument-functions -fno-omit-frame-pointer -fstack-usage -rdynamic \
    -o host_probe host_probe.c && ./host_probe boot_min.fs 2>host_probe.log >/dev/null
```

---

## 1. Answers

### 1.1 The table the brief asks for

| Item | Value |
| --- | --- |
| largest single frame | **`main` 96 B** (`ulp_stubs.c:45`, text 0xc44 = 3140 B — the whole engine inlined). Largest *non-root* frame: `find` 48 B |
| deepest chain | **`main` → `clit` → `cw` → `rd32` → `rd16` → `rd8` = 96+16+32+16+16+0 = 176 B** (tied: `main` → `find` → `rd32` → `rd16` → `rd8` = 176 B) |
| measured host delta, main → deepest callee | **368 B**, identical for all five P14 workloads (host build is instrumented, so its frames are ~30 B/function larger — §2.3) |
| interrupt frame (context save) | **68 B** (17 registers × 4 B, `ulp_riscv_vectors.S: save_general_regs`) |
| worst case incl. interrupt | **244 B** = 176 + 68 |
| recommended C stack + margin | **320 B**, i.e. **76 B spare** over 244 B |

No frame in the engine is unbounded: every `.su` line says `static`, there is no `alloca`, no VLA and no
local array — the largest local objects are scalars (`load()`'s 256-byte `char line[]` is host-only, not in
the ULP image, and it reports `352 dynamic,bounded`).

### 1.2 Every engine function's frame, from the compiler's own `.su`

`ulp_engine.su` — the exact P12 ULP build (`-Os -march=rv32imc_zicsr_zifencei -mdiv`). Verified
byte-identical in structure to P12's shipped object: `nm --print-size --size-sort` over
`idfproj/build/esp-idf/main/ulp_main/…/ulp_stubs.c.obj` and over `ulp_engine.o` differ in **no** symbol
size (`main` 0xc44, `word` 0xd8, `find` 0xaa, `pg_load` 0x76, `err` 0x5e, `rd32_paged` 0x4e, `rd16` 0x36,
`cw` 0x32, `wr16` 0x30, `wr32` 0x30, `rd32` 0x2e, `clit` 0x2a).

| function | source | frame B | kind |
| --- | --- | --- | --- |
| `main` | `ulp_stubs.c:45` | **96** | static — contains all of `interpret()`, `run()`, `forth_quit()` inlined |
| `find` | `uforth.c:170` | **48** | static |
| `pg_load` | `uforth.c:76` | 32 | static |
| `word` | `uforth.c:154` | 32 | static |
| `cw` | `uforth.c:199` | 32 | static |
| `mkhdr` | `uforth.c:223` | 32 | static |
| `rd16` | `uforth.c:55` | 16 | static |
| `wr16` | `uforth.c:58` | 16 | static |
| `rd32` | `uforth.c:59` | 16 | static |
| `wr32` | `uforth.c:60` | 16 | static |
| `rd32_paged` | `uforth.c:95` | 16 | static |
| `clit` | `uforth.c:200` | 16 | static |
| `a4` | `uforth.c:201` | 16 | static |
| `err` | `uforth.c:145` | 16 | static |
| `rd8` | `uforth.c:53` | **0** | static — `P()` and the load are inlined, no frame |
| `wr8` | `uforth.c:54` | 0 | static |
| `PUSH` | `uforth.c:105` | 0 | static |
| `RPUSH` | `uforth.c:109` | 0 | static |
| `forth_quit` | `uforth.c:378` | 0 | static — inlined into `main` |
| `pl_emit` | `ulp_stubs.c:23` | 0 | static |
| `pl_key` | `ulp_stubs.c:30` | 0 | static |
| `pl_hw` | `ulp_stubs.c:36` | 0 | static |

Cross-check that the root frame is not an artefact of where `main` lives: built **alone**
(`uforth.su`, no `main` at all, `forth_quit` as root) the engine's own root frame is **96 B** as well. The
number is the interpreter's frame, not the stub's.

### 1.3 The chain, summed from the relocation graph (not guessed)

Edges are `R_RISCV_CALL*` relocations in `ulp_engine.dis` (`chain.py`). A call GCC inlined leaves **no**
relocation, so the edges are exactly the calls that push a new frame — which is what makes "sum the `.su`
frames along the path" a bound and not a double count.

```
main -> { PUSH, RPUSH, a4, clit, cw, err, find, mkhdr, pg_load, pl_emit, rd16, rd32, rd32_paged,
          rd8, word, wr16, wr32, wr8 }
clit -> { cw, rd32 }        cw   -> { rd32, wr32 }      rd32 -> { rd16 }        rd16 -> { rd8 }
find -> { rd16, rd32, rd8 } mkhdr-> { err, rd32, rd8, word, wr16, wr32, wr8 }  pg_load -> { rd8 }
rd32_paged -> { pg_load }   word -> { wr8 }             wr32 -> { wr16 }        err -> { pl_emit, rd8 }
```

Per-function "own frame + best callee" (from `chain.py`):

| function | chain to leaf, B | function | chain to leaf, B |
| --- | --- | --- | --- |
| **`main`** | **176** | `rd32_paged` | 48 |
| `clit` | 80 | `rd32` | 32 |
| `find` | 80 | `wr32` | 32 |
| `cw` | 64 | `word` | 32 |
| `mkhdr` | 64 | `pg_load` | 32 |
| `a4` | 48 | `rd16` / `wr16` / `err` | 16 |

Deepest path, both ties named:

```
main (96) -> clit (16) -> cw (32) -> rd32 (16) -> rd16 (16) -> rd8 (0)  = 176 B
main (96) -> find (48) -> rd32 (16) -> rd16 (16) -> rd8 (0)            = 176 B
```

**The bound is 176 B.** The engine is not recursive (no cycle was found in the relocation graph), so no
call sequence can exceed the maximum path sum.

### 1.4 Host runtime check

`host_probe.c` `#include`s the engine, is built with `-finstrument-functions`, and records inside
`__cyg_profile_func_enter` the lowest stack address seen per workload, plus the address recorded on entry to
`main`. Both endpoints are taken from the same hook, so the hook's own frame cancels and the delta is a real
frame distance. Between workloads the record is reset; the dictionary is compiled once beforehand.

| workload (the five P14 named) | `interpret()` line | host delta B | deepest function |
| --- | --- | --- | --- |
| a primitive | `1 2 +` | **368** | leaf helper `P` (`rd8`'s callee) |
| a literal | `lit42` (`: lit42 42 ;`) | **368** | `P` |
| a colon call | `sq` (`: sq DUP * ;`) | **368** | `P` |
| a branch | `br` (`: br 0 0BR, ;`, `0BR,` = `['] 0BRANCH , 0 ,` immediate) | **368** | `P` |
| page fault path | `3 fetch` (`: fetch @ ;`) — and, in fact, every token fetch | **368** | `P` |

All five are equal because every one of them ends in the same place: whatever the dispatch does, the fetch
`rd32_paged(w)` → `pg_load`/`resolve` → `rd8` → `P` goes through the paged accessor, and `word`/`find` do
the same on the way in.

The matching static prediction on that same instrumented host binary (`host_probe.su` + `host_probe.dis`,
parsed with the same tool) is **464 B** for the engine's maximum path
`main(128) + interpret(64) + run(96) + rd32_paged(32) + resolve(32) + pg_load(48) + rd8(32) + P(32)`, and
**≥ 368 B** for the path that was observed. So the runtime distance (368 B) sits **below** the static bound
(464 B), by 96 B = 21 %: the accounting rule never *understates* the stack, which is the direction a bound
has to be wrong in. Note the host frames are not the ULP frames (instrumented, x86-64, `-Os`): the host run
validates the *method*, not the 176 B — the 176 B is the cross-compiler's own number for the shipped object.

### 1.5 The interrupt path

`-fstack-usage` cannot see it because it is assembly, so it is read off the source:

```asm
.equ SAVE_REGS, 17
.equ CONTEXT_SIZE, (SAVE_REGS * 4)      /* = 68 */
.macro save_general_regs cxt_size=CONTEXT_SIZE
    addi sp, sp, -\cxt_size             /* 68 B on the SAME stack as the interpreter */
    sw   ra, 0(sp) ... sw t6, 64(sp)
```

`CONFIG_ULP_RISCV_INTERRUPT_ENABLE=y` compiles `irq_vector` with `save_general_regs` (17 × 4 = **68 B**:
`ra, tp, t0-t6, a0-a7`), then `jal _ulp_riscv_interrupt_handler` — so the C handler and anything it calls
land **below** those 68 B. The save is unconditional and happens at whatever depth the interpreter had
reached, so it must be added to the *worst* interpreter depth:

```
worst case = 176 (deepest chain) + 68 (irq_vector context save) = 244 B
```

and the C handler's own frame is *additionally* on top of that (see §5, item 1 — it is not in this build).

### 1.6 Recommendation

**C stack = 320 B.** Margin **76 B** over the 244 B worst case, and the margin is for exactly three things:

1. the `_ulp_riscv_interrupt_handler` C frame plus the probe's own handler body, which is **not** measured
   here (§2.4): 68 B of vector save is the floor, not the whole interrupt cost;
2. compiler drift — a flag change (e.g. dropping `-Os`, or the engine getting one more nested helper) moves
   a frame by 16–48 B, which is 1–2 frames of the measured chain;
3. a guard band at the bottom of the pool, so a one-frame overrun lands in padding rather than in the
   neighbouring Forth structure.

Against §4.3: 400 → **320 B** returns **80 B** to the resident dictionary. **Do not** go to the brief's
"256 B with 100 B margin" branch: that branch is conditional on the chain being ≤ 150 B, and it is **176 B**,
so 256 B would leave only 12 B of margin once the interrupt save is included — i.e. the interrupt handler
would be running on the guard band.

---

## 2. Evidence

### 2.1 Why the build is the shipped build

`riscv32-esp-elf-gcc 14.2.0 (esp-14.2.0_20241119)`, flags taken verbatim from
`idfproj/build/esp-idf/main/ulp_main/compile_commands.json` of P12 (`-DIS_ULP_COCPU
-DULP_RISCV_REGISTER_OPS -Os -march=rv32imc_zicsr_zifencei -mdiv -fdata-sections -ffunction-sections`).
`nm --print-size --size-sort` on P12's real `ulp_stubs.c.obj` and on `ulp_engine.o` agree on every symbol
size, so the `.su` frames describe the image P12 measured at 3986 B, not a different build.

`main` is one 3140 B function because `interpret()`, `run()` and `forth_quit()` are all inlined into it —
the engine's *interpreter loop* is the frame, which is exactly why its 96 B is the largest frame in the
system.

### 2.2 `.su` qualifiers: nothing unbounded

Every engine line is plain `static` (no `dynamic`, no `bounded`). The only `dynamic,bounded` lines in the
host build are `load()` (`char line[256]`) and the harness — both host-only code paths, absent from the ULP
image (`load()` and the `HOST` section are compiled out; `nm` on `ulp_engine.o` has no `load`).

### 2.3 Host instrumentation, honestly described

`-finstrument-functions` inserts a call at every entry, so the host `.su` frames are inflated relative to an
uninstrumented build (`rd8` 0 → 32, `interpret` — inlined on the target — 64, `main` 112/128 vs the ULP's
96). That is why the host delta (368 B) is *not* compared to the 176 B directly: it is compared to the host
static bound (464 B) built from the same instrumented objects. `dladdr` resolved the deepest pointer to `P`
only after `-no-pie` (with a PIE binary the recorded pointer is load-base-relative, and the name lookup
silently returned `?` — a lookup that fails open is worth flagging).

### 2.4 What failed / was not measured

* **The C interrupt handler's frame is not measured.** `ulp_riscv_interrupt.c` compiled with the P12 ULP
  include set produced an **empty** `.text` (804 B object, no code): P12's `sdkconfig` has
  `# CONFIG_ULP_RISCV_INTERRUPT_ENABLE is not set`, so the handler is compiled out and the vector save is
  not even in the 3986 B image. Turning that config on and re-linking is a separate measurement (follow-up
  1); it does not change the vector save (68 B, read from the macro) but it does add the handler frame on
  top of 244 B. This is precisely what the 76 B margin is for.
* **`boot_min.fs` is 16-bit.** Its `IF/THEN/ELSE` emit 2-byte operands with `W,`/`W!`; on this 32-bit
  engine they misbranch (`errf` set, empty stack). The branch workload was therefore compiled with the
  32-bit `,` primitive instead. A 32-bit boot layer for the host harness does not exist in P12's tree.
* **No workload reached a *different* depth.** All five report 368 B. That is the honest result (one
  fetch path dominates), but it means the "five workloads" requirement is satisfied by five runs of *the
  same* deepest path, not five distinct paths.

### 2.5 Why this overran the box

The overrun is the dladdr/`-no-pie` retry and the two attempts at `ulp_riscv_interrupt.su` (§2.4) — not the
measurement itself, which needed one compile, one `objdump` and one host run. The numbers above are all from
the single first-pass build; only the *naming* of the deepest host function and the *interrupt handler*
attempt were re-run. Nothing was tuned towards 400 B: the 176 B is what the compiler reports.

---

## 3. Verdict

**PASS**, and the §4.3 line moves, downward.

* deepest static chain **176 B**, named and summed from the compiler's own `.su` output;
* largest single frame **`main` 96 B** (the inlined interpreter);
* no unbounded frame — nothing to fix before a size claim;
* interrupt save **68 B** added on top → **244 B** worst case;
* recommendation **320 B**, 76 B margin, **80 B back to the dictionary**.

The brief's first failure criterion does **not** fire (244 < 400), and its second does **not** either
(176 > 150): the correct action is neither "keep 400" nor "drop to 256", it is 320 B. Note this is 4 % of the
482 B shortfall in §4.3 — the C stack was never where the bytes were.

---

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §4.3 — the C-stack row of the table (line `| C stack + guard | 400 | 400 |`)

Replace the row with:

```
| C stack + guard | 400 | **320** (measured worst case 244 B = 176 B deepest static chain + 68 B interrupt save, `P21`) |
```

And, immediately after the table (before "**The dictionary needs more than 614 B.**"), the subtotal and
headroom lines change: subtotal 7562 → **7482**, "Left for the resident dictionary" 614 → **694**, and the
shortfall sentence 482/1342 → **402 B at best and 1262 B at worst**. The settled measurement text to add:

> The C stack is **244 B worst case, not 400**: the deepest static call chain from `main` is
> `main → clit → cw → rd32 → rd16 → rd8` = **176 B** (compiler `.su` frames summed along the
> relocation-forced call graph; `main`'s own frame is 96 B and holds the inlined interpreter), plus the
> **68 B** register save that `ulp_riscv_vectors.S` puts on the same stack when an interrupt lands.
> A 320 B line therefore carries a **76 B margin**, reserved for the IDF interrupt handler's own frame,
> compiler flag drift and a guard band at the bottom of the pool (P21).

### 4.2 `probe/EVIDENCE.md` — a new entry

```
## P21 — C stack: 176 B static chain, 244 B worst case, 320 B recommended

`-fstack-usage` on the P12 ULP build (3140 B `main`, the interpreter inlined) + the call graph from
`R_RISCV_CALL*` relocations. Largest frame **`main` 96 B**; deepest chain
`main → clit → cw → rd32 → rd16 → rd8` = **176 B**; `ulp_riscv_vectors.S` adds **68 B** on the same stack
⇒ **244 B worst case**, so §4.3's 400 B line is 156 B too large and **320 B** (76 B margin) returns
**80 B** to the dictionary. Host `-finstrument-functions` cross-check: 368 B measured, against a 464 B
static bound for the same instrumented binary — the bound is never exceeded. The IDF interrupt handler's
frame is *not* measured (P12 has `CONFIG_ULP_RISCV_INTERRUPT_ENABLE=n`); the margin covers it.
See `probe/results/P21-c-stack/RESULT.md`.
```

---

## 5. Follow-ups

1. **Rebuild P12 with `CONFIG_ULP_RISCV_INTERRUPT_ENABLE=y`** and add `-fstack-usage` to the ULP component,
   to get `_ulp_riscv_interrupt_handler`'s real frame (and the probe's own handler body). That single number
   is the only gap between 244 B and a fully measured worst case; until then 76 B of the 320 B is the
   estimate.
2. **`SD` and the C stack are independent**: P13's 128 B of Forth stacks is a different budget line; do not
   trade between them.
3. If the dictionary needs the last 16 B, 304 B (60 B margin) is still defensible *after* follow-up 1 lands
   and shows a handler frame ≤ 60 B — not before.
