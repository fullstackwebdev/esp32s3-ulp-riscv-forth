# P01 — Engine size and whether the resident budget closes

| | |
| --- | --- |
| Runs on | **host only** (needs the RISC-V toolchain, not the board) |
| Time box | **15 min**, one run, hard cap |
| Depends on | — |
| Blocks | everything: the 4-frame vs 2-frame decision, `01-proposal.md` §4.3 |
| Serves | R1 (engine contains no user words), open question Q3 |

## Timebox — 15 minutes, one run, no slices

* **Hard cap: 15 minutes total**, from the first command to the written `RESULT.md`.
* **At T−2 minutes stop starting new work.** Wrap up, write `RESULT.md`, kill processes, kill the tmux
  session.
* **It all has to fit.** A cold ESP-IDF build is 2–3 minutes and a flash ~20 s, so if the probe needs
  a build, start it in the first five minutes — not at minute ten.
* **Every command carries `timeout`**: builds `timeout 300`, device ops `timeout 30`, host test runs
  `timeout 20`. No bare long-running command, no `&`, no `nohup`, no `/tmp`.
* **Every loop is bounded twice**: by iteration count *and* a wall-clock check inside the loop.
* **A hang is a `FAIL`**, with the exact command and the last output recorded.
* **If the question does not fit in 15 minutes, the question is too big.** Report what was measured;
  the orchestrator will cut a narrower question. Running the same probe again is not the answer, and
  splitting a probe into slices is not the answer either.

## Question

How many bytes is the **engine** — token interpreter, primitives, parser/`FIND`/`NUMBER` — when
built for `rv32imc` with the ULP toolchain, excluding the Forth memory array? And with that number,
does the §4.3 resident budget close with 4 page frames of 512 B?

## Why it matters

§4.3 currently asserts a total of ~6400 B leaving ~1750 B for the resident dictionary. That number
is a guess. If the engine is 4 KB, the dictionary loses 1.4 KB and the prelude may not fit resident —
which changes the frame count, the page size, or both. This is the cheapest probe to run and it can
falsify the plan before any hardware work.

## Method

1. Create `probe/results/P01-engine-size/` and copy `probe/uforth/uforth.c` there. **Do not modify
   the original.**
2. Write a stub `ulp_stubs.c` providing only what the ULP build needs: `pl_key`, `pl_emit`, `pl_hw`
   (each a trivial register/ring access placeholder is **not** acceptable — implement `pl_emit` over
   a write to a global ring head, `pl_key` returning `-1`, `pl_hw` returning 0), plus
   `int main(void)` that calls `interpret()` once after seeding the input buffer with a short line.
   The stub's own size must be reported separately so it can be subtracted.
3. Build the interpreter object with the exact IDF flags:
   `riscv32-esp-elf-gcc -Os -march=rv32imc_zicsr_zifencei -mdiv -fdata-sections -ffunction-sections -c`
   and link with the ULP linker script. Two acceptable routes:
   - **Preferred:** a throwaway IDF project using `ulp_embed_binary`, so the size comes from the
     supported path (`build/esp-idf/main/ulp_main/ulp_main.map` and `ulp_main.bin`);
   - **Direct:** link with `-T components/ulp/ld/ulp_riscv.ld -nostartfiles --specs=nano.specs
     --specs=nosys.specs -Wl,--gc-sections`, with `CONFIG_ULP_COPROC_RESERVE_MEM` defined (the
     linker script includes `sdkconfig.h`).
   Record which route you used.
4. Measure and record:
   - `.text`, `.rodata`, `.data`, `.bss` totals from `riscv32-esp-elf-size -A`;
   - `.bin` size;
   - `.text` **excluding** the stub (subtract the stub's own symbols);
   - the ten largest symbols by size (`nm --size-sort`);
   - the same build with `-DMEMSZ=2560` and `-DMEMSZ=4096` (the array is `.bss` when `IMAGE` is not
     defined, so it should not inflate `.bin` — prove that).
5. Compute the §4.3 table with your measured engine number and state the resulting dictionary
   headroom for 4 frames and for 2 frames.
6. Verify R1's first acceptance item: `nm` on the ULP ELF must show **no** Forth word symbols (no
   `SQ`, no `DUP_HEADER`, nothing from the prelude) — only C symbols.

## Record

A table: engine bytes (text/rodata/data/bss), stub bytes, blob bytes at MEMSZ 2560 and 4096, the ten
largest symbols with sizes, dictionary headroom for 4 and 2 frames, and the route used (IDF project
or direct link).

## Pass criteria

* engine `.text + .rodata` measured, reproducible from the recorded command line;
* headroom computed for both frame counts;
* `nm` shows no prelude symbols (R1 item 1 satisfied on the host side).

## Failure criteria — and what each changes

* **Engine > 3.0 KB** ⇒ `01-proposal.md` §4.3 switches to 2 frames (1 KB) and the dictionary gains
  1 KB. State the new table.
* **Engine > 4.0 KB** ⇒ this is the §12 stop condition: the resident design does not close. Report
  it as `FAIL` with the measured number and do not attempt fixes.
* **`MEMSZ` inflates the blob** ⇒ the "array is `.bss`" assumption is wrong; the dictionary must be
  zero-filled at boot by the server instead of being part of the image. Report which and why.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.3 — replace the estimated engine row with your number, and the "If the
  measured engine exceeds 3.0 KB…" sentence with the actual decision taken.
* `docs/00-background.md` C11 row in the corrections table — replace "to be measured" with the
  measured figure.
* `probe/EVIDENCE.md` — new entry `E-007` with the numbers and the command.

## Do not

* Do not add primitives, shrink features, or "optimise a little" to make a number fit. Measure what
  the design needs, then report honestly.
* Do not touch the board.
* Do not edit `docs/` or `probe/uforth/uforth.c`.
