# P14 — What does one token cost in cycles?

| | |
| --- | --- |
| Runs on | **host only** (compile for rv32, disassemble, weigh against P05's measured costs) |
| Time box | **15 min**, one run, hard cap |
| Depends on | P05 (per-instruction cycles), P04 (505-dispatch token) |
| Blocks | the connected-mode period in §8; whether typing can feel instant |
| Serves | R2, R3 |

## Question

P04 counted **dispatches**, P05 measured **cycles per instruction class**. Nobody multiplied them.
How many cycles does one primitive dispatch cost, and one colon-word call, on this core — and what
wake length does a 4-token slice of typing therefore need?

## Why it matters

This is the difference between a terminal and a fax machine. If a dispatch is 60 cycles, a 22-tick wake
(2 697 cycles) retires ~43 dispatches: interactive. If a dispatch is 300 cycles, the same wake retires
8, and typing needs 100-tick wakes (0.65 ms) or the REPL visibly lags. Every "feels immediate" claim in
§8 rests on this number, and none exists.

## Given — do not re-derive

* P05: dependent ALU **4.0** cycles, RTC-RAM word load **8.1**, byte load **8.6**, wake entry **81**.
  Core **19.0 MHz**. Tick **122.6 cycles**. Period floor **22 ticks** (P06).
* P04: a step retires ≤ 16 tokens; one token can cost **505** dispatches; ring/period chosen at `k=4`.
* 32-bit references (P02), so a token fetch is a 4-byte load and an operand is 4 bytes.

## Method

1. Copy P02's 32-bit `uforth.c` into `probe/results/P14-cycles-per-token/`.
2. Compile it for the target with the ULP flags (`-Os -march=rv32imc_zicsr_zifencei -mdiv`), with
   `-ffunction-sections`, and **disassemble** with `riscv32-esp-elf-objdump -d`.
3. Enumerate the **exact instruction sequences** for these paths and count them, line by line:
   - `NEXT` (fetch token + descriptor + jump), which every dispatch pays;
   - a stack primitive (`DUP`), a memory primitive (`@` through the byte-wise accessor **and** through a
     native `lw`, so D7's 8.5× penalty is quantified in context);
   - a colon-word entry (`P_DOCOL`), and `P_EXIT`;
   - `0BRANCH` taken and not taken;
   - the `switch` dispatch itself (jump table + bounds).
4. Weigh each instruction by P05's measured class cost (ALU 4, word load 8.1, byte load 8.6, store the
   same as load, branch 4) and produce **cycles per dispatch** and **cycles per token** with the
   breakdown, including a best case (all ALU) and a worst case (every operand a byte-wise access).
5. Multiply by P04's numbers: cycles for a `k=4` slice of ordinary typing, and cycles for the
   505-dispatch token. Convert to **ticks** and **µs** at 122.6 cycles/tick.
6. State the practical consequence: the minimum wake period for (a) interactive echo, (b) compiling one
   line from the prelude, (c) running a 100-iteration loop.

## Record

| Path | instructions | weighted cycles |
| --- | --- | --- |
| `NEXT` | | |
| `DUP` | | |
| `@` byte-wise / native | | |
| `P_DOCOL` / `P_EXIT` | | |
| `0BRANCH` taken / not | | |
| **cycles per dispatch (best / typical / worst)** | | |
| **cycles per token** | | |
| 4-token slice → ticks / µs | | |
| 505-dispatch token → ticks / ms | | |

## Pass criteria

* every path has an actual instruction listing from the disassembler, not an estimate from reading C;
* the weighting uses P05's measured class costs, and the arithmetic is shown;
* the three consequences are stated in ticks and µs.

## Failure criteria — and what each changes

* **Cycles per dispatch > 200** ⇒ interactive echo needs ≥ 100-tick wakes (0.65 ms). §8's connected
  mode changes, and the "feels immediate" claim is only true because of typing latency hiding — say so
  plainly rather than claiming 0.2 ms.
* **`NEXT` dominates (≥ 50 % of a dispatch)** ⇒ the interpreter's dispatch loop, not the primitives, is
  the optimisation target. That reorders the whole optimisation plan: token threading would help more
  than native accessors.
* **Byte-wise `@`/`!` more than doubles a dispatch** ⇒ D7 becomes not just required but *first*, before
  any other performance work.
* **A 505-dispatch token exceeds a 22-tick wake by more than 10×** ⇒ the wake budget cannot simply be
  "retire k tokens"; the dispatch budget must be the primary limit (§5 already says this, but the factor
  becomes a number).

## Doc deltas to hand back

* `docs/01-proposal.md` §5 — the dispatch budget with real cycle figures.
* `docs/01-proposal.md` §8 — the connected period, restated from the measurement.
* `docs/03-prototype-review.md` D7 — confirm or reorder the optimisation priority.

## Do not

* Do not measure anything on the board; this is a static accounting exercise against measured constants.
* Do not estimate instructions from the C source — use the disassembly, or say which path you could not.
* Do not touch `docs/` or other probes' directories.
