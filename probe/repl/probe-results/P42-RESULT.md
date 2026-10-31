# P42 — RESULT: does a halfword token fetch pay? **YES — 35.2 % faster dispatch**

> **Attempt 2 (this section) measured it, and adopted the change.** Attempt 1 (kept below) obtained no
> measurement: its harness corrupted the machine. Read attempt 1 only for the failure modes.

## Attempt 2 — PASS

Method, per the requirements written after attempt 1:

* the bench runs **once from `main()`, at boot**, before the REPL loop or any drain exists;
* the workload is **colon words** (`1+` = `: 1+ 1 + ;`), because primitives never fetch a token — attempt 1
  timed dictionary lookup by accident;
* **dispatches are counted** by a `-DP42_COUNT` counter in `vm_enter()`, present in both images;
* **two line lengths** (20 and 40 `1+`), so the per-call overhead cancels and the slope is cycles/dispatch;
* the harness **validates before timing**: one pass must leave `errf == 0`, `sp == 0`, `rsp == 0`, `ti == tl`;
* output is hex via a 40-byte printer, never through `interpret()` — asking the engine to format a number
  pulled a second copy of the interpreter into the image (8 010 B against a 7 856 B pool), and the bench then
  trampled its own C stack. That was attempt 1's `min=567`.
* the bench image is **`-DP42_ONLY`**: it reports and retires, so `drain_cmd`/`run_line` are unreferenced and
  removed by `--gc-sections`, which is what brings it inside the pool (7 694 / 7 700 B).

### Measured, twice each, bit-identical across boots

| Image | short (81 disp) | long (161 disp) | **cycles/dispatch** | intercept |
|---|---|---|---|---|
| baseline `rd16` = 2 x `rd8` | 193 928 | 334 548 | **1 757.75** | 51 550 |
| variant `rd16` = 1 x `lhu` | 122 804 | 213 944 | **1 139.25** | 30 525 |

**−618.5 cycles per dispatch = −35.2 %.** `err = 0` in both, identical dispatch counts, reproducible exactly
across reboots (no cache, no interrupts, so the measurement is deterministic).

### Why the win is this large

1 758 cycles per dispatch for a two-byte token is ~24 cycles per instruction (P14's figure, E-052). `rd16` used to
make **two `rd8()` calls**, each a `jal`/prologue/bounds-check/load/`ret` — roughly 8 instructions apiece with
nothing to hide the latency. Removing one call removes ~600 cycles. The prediction that "removing one load is a
latency question, not an instruction-count question" was right, and the answer was much larger than the 12-byte
code saving suggested.

### Adopted

`src/uforth.c`: `rd16` is now one halfword load (with an `ALIGN_TRAP` build option that halts on an odd address
instead of returning a byte-swapped value, and no silent byte-pair fallback). Shipping image **6 112 B**,
pool **7 264 B** of 7 856 (**+6 B** for a 35 % win), and verified on the board: `2 3 + .` → `5 ok`,
`: SQ DUP * ;` → ` ok`, `7 SQ .` → `49 ok`, `: CUBE DUP DUP * * ;` → `3 CUBE .` → `27 ok`,
`BOGUS` → `BOGUS?`, `21 D2 .` → `42 ok`.

### Residual risk, named

Alignment is asserted by construction (tokens/cells are only written through `wr16`/`wr32` at even addresses) and
observed over ~10 000 dispatches with no trap, but it is **not proven for every call site**: `rd16` is also used
for dictionary link fields. The `ALIGN_TRAP` build exists to settle that in one run.

---

# Attempt 1 — INVALID (kept as the record of the failure)

| | |
|---|---|
| **Question** | `rd16` spends `lbu,lbu,shift,or` on every token, and token fetch is 90.9 % of the dispatch cycle (F-18). Does replacing it with one aligned `lhu` move `NEXT`? |
| **Answer** | **Unknown.** The bench harness corrupted the machine it was measuring. Two runs produced self-contradictory numbers and left the REPL unable to answer. No cycle comparison between the two images exists. |
| **Verdict** | **INVALID — not a negative result.** The question is still open. |
| **Time** | one run, ~35 min (over budget; two rebuild cycles caused by harness defects) |

## What was built

* `src/ulp_repl.c` gained a `BENCH` command: it loads a fixed line into `tib`, times `interpret()` with `rdcycle`,
  repeats 100×, reports the minimum.
* Variant image: `probe/isa/lhu/` — same tree, `rd16` replaced by `a + 1u < MEMSZ ? *(volatile u16 *)(mem + a) : 0u`
  (single halfword load, no masking, no byte-pair fallback).
* Both images built; `CMakeLists.txt` gained `REPL_ULP_SRC` for selecting an alternative ULP source.

## What happened, in order

1. **First workload was invalid.** `1000 BEGIN 1- DUP 0 = UNTIL DROP` — `BEGIN`/`UNTIL` are compile-only, so typed
   at the interpreter they do nothing. Measured 141 684 cycles for a "1 000-iteration loop". Direct check:
   `3 BEGIN 1- DUP 0 = UNTIL DROP .` printed `3`, i.e. the loop never ran.
2. **Second workload, stack-neutral and loop-free** (`1 DUP + DROP` × 9 = 117 chars): reported
   `min=567..568 cycles for 100 repetitions`, `err=4`, `sp=0`. 567 cycles is ~6 per repetition — the interpreter was
   returning immediately, and `errf` (a 0/1 flag) read as 4.
3. **The machine stopped answering.** After that run, typed lines echoed but produced no `ok`; replies arrived late
   and batched, and repeated `BENCH` lines were served several at a time. The ULP was stalling for long stretches,
   not erroring.
4. **Harness removed, image restored.** The bench was gated behind `-DP42_BENCH`; the shipping build is now
   `6 108 B` (pool **7 258 B** unchanged) and answers `2 3 + .` → `5 ok`, `7 SQ .` → `49 ok`, `BENCH` → `BENCH?`.

## Leading hypothesis (not yet tested)

`interpret()` is a re-entrant call in this engine: it owns `tib`/`ti`/`tl`/`errf` and, on error, does `ti = tl`.
The bench calls it from inside `drain_cmd()`, which is itself inside `main()`'s drain loop and has already consumed
part of the ring — the same parser state the bench then overwrites 100 times. `saynum()` then calls `interpret()`
again to print each number. So the diagnostic re-enters the parser ~104 times in the middle of a drain, and the
`err=4` / stall pattern is consistent with the parser and the ring positions disagreeing rather than with a
cycle-count problem.

Nothing here says anything about `lhu`. The size half of the claim is measured and stands: **−12 B of `.text`**
(F-63, E-052).

## What the next attempt must do differently

1. **Do not call `interpret()` from inside the input path.** Time the workload from `main()` *before* the first
   drain, or from a dedicated one-shot that runs once, reports, and only then enters the REPL loop.
2. **Assert the harness before trusting it:** run one iteration of the workload, check `sp`/`errf` are clean *and*
   that `ti == tl` (parser consumed the whole line), and only then loop.
3. **Count tokens, don't assume them.** Put a `u32` counter increment in `interpret()`'s loop for the bench build
   only; ~2 cycles/token against a ~700-cycle token is a 0.3 % perturbation, applied identically to both images.
4. **Two-point linearity**: same line at 4 and 8 groups, so the fixed per-call overhead cancels and the slope is
   cycles per token.

## Artifacts

* Restored image: `build/esp-idf/main/ulp_main/ulp_main.bin` (6 108 B), `build/flash_args`.
* Failed variant source: `probe/isa/lhu/` (`rd16` = single `lhu`, tag `p42 lhu`), bench-gated.
* Raw captures: `probe-results/p42_lhu.txt`, and the transcripts quoted above.
