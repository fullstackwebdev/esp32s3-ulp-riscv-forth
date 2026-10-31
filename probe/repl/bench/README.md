# bench — the acceptance surface

Four Forth workloads that answer one question: **did the engine's behaviour change?** They exist so that
optimising this machine has a referee, and so that "it feels faster" never has to be an argument.

```
./bench/run.sh              # compare against bench/baseline.txt  (exit 1 on any change)
./bench/run.sh --freeze     # rewrite the baseline — a deliberate act, after understanding a diff
```

## The three units, and why these

| unit | exact? | why it is the right one |
| --- | --- | --- |
| **result** | yes | each workload prints a checksum. A wrong answer is a failure, not a slow pass. |
| **DISP** | yes | dispatches executed, from the engine's own counter (`-DP42_COUNT`). Identical on any host, so it cannot drift with machine load; it moves only when the engine's work per operation changes. |
| **limits** | yes | the depth ladder and the byte counts are integers. Only integers are comparable for equality. |

**Wall-clock is deliberately not compared.** The host is a 100× faster CPU with a cache; a millisecond
measured here says nothing about 19 MHz with no cache, and it drifts with whatever else the machine is
doing. Wall-clock is for the *board*, where cycles are read from `rdcycle`; it has no place in a test that
has to pass on every run.

Every DISP number is reported **minus the prelude baseline** (~261 dispatches to load the 85-word
vocabulary), so a workload's cost is not polluted by unrelated changes to the prelude.

## The workloads

| file | stresses | expected |
| --- | --- | --- |
| `arith.fs` | one multiply and one add per iteration, 1 000 times | sum 1..1000 of i², mod 1 000 003 = **832501** |
| `matrix.fs` | 2×2 multiply, 500 times: 8 multiplies + 6 adds per iteration, no variables | trace 134 × 500 = **67000** |
| `recursion.fs` | exponential call pressure, 465 calls for one answer | fib(12) = **144** |
| `depth.fs` | the deepest legal recursion **and** the refusal beyond it | `0` then `ERR_STACK` |

## What the dialect allows (learned the hard way)

These cost runs to discover and are the rules any new workload must follow:

1. **`BEGIN…UNTIL` / `IF…THEN` are compile-only.** Typed at the prompt they do not loop — the body runs
   once and prints a plausible wrong number. **All loops live inside a colon definition.**
2. **No `R@`,** only `>R` / `R>`. A base address goes in a constant or on the data stack, not in a return
   cell you intend to read.
3. **No `ALLOT`, no `FILL`, no `DO…LOOP`.** Space is reserved with `,` (one cell at a time).
4. **`CONSTANT` takes its value from the stack**, so `0 BLOCK CONSTANT BUF` names a buffer in one line —
   whereas `HERE CONSTANT BUF` names a cell that the *next* definitions will occupy.
5. **Reserve first, capture after.** A word that reserves must push the base it used
   (`: RESERVE HERE 0 BEGIN DUP , … UNTIL DROP ; RESERVE CONSTANT BUF`), or the buffer and the code that
   uses it are the same bytes.
6. **A wide expression is a stack-depth bug.** Eight live products before the reduction overflowed 16
   cells; one colon word per matrix entry fixed it.

## Pending — `pending/memory.fs`

The memory-bandwidth workload is written and **blocked by an engine defect it found** (E-081): calling a
`CONSTANT` (a DOCON word) from inside a colon definition **underflows the stack**. A colon word called the
same way is fine, so it is specific to DOCON. The file is kept because it is the reproduction; the number
stays unmeasured rather than invented from a failing run.

## What is not here yet

- **Dictionary exhaustion**: define words until `ERR_DICT` and report bytes/word. Needs a generated file
  and a binary search, so it belongs in `bench/limits.sh` rather than in a `.fs`.
- **Program-size accounting**: the same probe answers "how many bytes does a definition cost".
- **On-chip numbers**: dispatch counts are portable but *cycles* are not. The board run
  (`probe/repl/probe-results/`) is where 1 139 cycles/dispatch and 1 623 per typed literal come from.
