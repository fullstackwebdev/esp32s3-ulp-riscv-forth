# Autoresearch: application space for the ULP Forth, in bytes

## Objective
Maximise **application space** — the free gap inside `mem[]` between the code area and the newest dictionary
header — in the interpreted Forth that runs on the ESP32-S3 ULP coprocessor. Every feature must survive: all
85 words, blocks, tasks, the REPL, and the image must still work **on the device**. Speed is not the goal;
an idea that costs cycles is acceptable when it buys bytes, and ideas that win both rank first.

Why bytes anywhere become app space: `app space = MEMSZ − BLKSZ − headers − code`, and `MEMSZ` is capped by
the pool (`text + rodata + data + bss ≤ 7 856`). So **1 byte saved in `.text`/`.rodata`/`.bss` = 1 byte of
application space**, after a re-bake at the raised `MEMSZ`.

## Metrics
- **Primary**: `app_bytes` (bytes, **higher** is better) — the bake's own `free` count at the largest `MEMSZ`
  the pool allows.
- Secondary: `text`, `rodata`, `bss`, `pool`, `memsz_max`, `words` (must stay 85).

## How to run
`./.auto/measure.sh` — twin-builds `probe/repl/src` with the shipping flags and link line (~2 s), computes
the largest fitting `MEMSZ`, bakes into `.auto/tmp`, and prints `METRIC name=value` lines. It never touches
`src/image.h`. `.auto/checks.sh` runs the 12-check host suite and the 5-workload bench (checksums and DISP
must be identical).

## Files in scope
- `probe/repl/src/uforth.c` — the engine: dispatcher, primitives, dictionary, accessors, tasks
- `probe/repl/src/ulp_repl.c` — ULP harness: flags (`MEMSZ`, `BLKSZ`, `NTSK`, `TIBSZ`, `P54_BINOPS`), rings, `main`
- `probe/repl/src/p31_cases.inc`, `p33_cases.inc`, `p54_cases.inc`, `p54_ops.h`, `p*_prims.inc` — case bodies and the primitive table
- `probe/repl/src/p39_prelude.fs` — the baked prelude (Forth source)
- `probe/repl/src/image.h` — baked dictionary; **only** regenerate it via `tools/bake.sh`, never by hand
- `probe/repl/tools/measure.sh`, `probe/repl/tools/bake.sh` — the twin harness and the bake (one owner each)
- `probe/repl/tests/*`, `probe/repl/bench/*` — tests and the acceptance surface

## Off limits
- `cache/` — write-once fetch cache, never pruned.
- `probe/results/`, `probe/repl/probe-results/`, `archive/` — evidence; append, never rewrite.
- `docs/`, `CONSTRAINTS.md` — update them to match reality, but the *numbers* there must stay measured.
- Any feature: no word removed, no buffer shrunk, no concurrency lost, no capacity reduced.
- The benchmarks must not be edited to pass (no new goldens unless the change genuinely alters the token stream, and then say so).

## Constraints
- Every code edit carries `// GUARDRAIL: <lesson> — <reason> — <fix>`.
- Fail loud: no silent defaults, no placeholder values, no mocks.
- `#define X 0` does **not** disable `#if defined(X)` — comment the define out instead (cost two builds once).
- The bake and the build must agree on `MEMSZ` **and** every flag that shapes the dictionary.
- Board verification on every `keep`: `10 FIB .` → 55, `15 FIB .` → `ERR_STACK`, `0 BLOCK .` → `BLKADR`,
  a `SAVE` + `BLOCK C@` round trip, two tasks printing, `2 3 + .` → 5 afterwards. Flash `/dev/ttyACM1` only.
- Do not overfit the benchmarks and do not cheat them: the acceptance surface is checksums and dispatch
  counts, so any change that alters DISP must be a deliberate, explained change with the baseline re-frozen.

## What's been tried
Harness facts established first: RVC is saturated (933 of 1 698 instructions are 2-byte, 2.90 B/instr), the
ULP links at 0 so addresses are small (only 120 `lui`), `DICT` 56 has no free bytes (vars 0–21, `PAD` 24–55),
and 2-byte dictionary headers are arithmetically impossible (need `xt` 10 bits + imm + hash).

Adopted so far (before this session): `-msave-restore` (−224 B text), hash dictionary (−406 B dictionary),
one-byte message codes (−104 B rodata), `NTSK` 3→2 (−140 B bss), `P30_HANDCOPY` (−356 B), `lhu` fetch
(−35 % dispatch cycles), number-first parse + direct `find` (17.3× on literals), 4-byte→3-byte headers
(−85 B dictionary), a table-driven kernel for 10 same-shape primitives (−224 B pool, dictionary
byte-identical), a shared tail for the error paths (−52 B). Total: app space 154 → 727 B.

Killed, do not retry without new evidence: 1-byte tokens (ceiling 118 B; prototype −44 B for +352 B),
merged rings (64 + 128 are already one contiguous 192 B block), unchecked accessors (−58 B but unsafe),
`-fno-jump-tables` (+88 net), `-Oz`/`-flto`/`-fno-builtin` (0 B), primitive subset and `NTSK` 1 (remove
features), `SD 32` (+394 B), paging/overlays.

**The file is at a local optimum in C.** Three consecutive local edits regressed, all measured:
`LIT2`/halfword literals (732 and 731 B), inlining the 9 PAD-relative accesses to skip `rd8`/`wr8`'s bound
check (637 B — the shared callee wins because the call site pays the same address materialisation and the
callee's test is shared across ~100 sites), and `-msmall-data-limit=2048` (0 B: the toolchain emits no
`gp`-relative reference on this target). **Do not edit C locally for bytes; only removing redundant work
has paid** (scheduler unroll +8, single status read + error-exit merge +6).

A fourth shape pays — **hoisting per-token memory traffic into registers** — but only where the flush
surface is small: `w`/`ip` are `u16` fields of `VM` and hoisting them into the dispatch loop's locals (3 flush
points) gave **+16 B and two fewer round-trips per token**. `sp`/`rsp` cannot follow the same route because
`PUSH`/`POP` are out-of-line functions that write `V->SP` directly, so hoisting them would force ~100 inlined
call sites.

Also measured and rejected: folding the name hash into the `PAD` copy (deleting the 44 B `hash_pad` cost +36 B
of text, because the hash chain then has to exist in two places — typed path and boot path — and each inline
djb2 is ~40 B). That variant was **correct** (12/12 suite, bench identical) and one walk faster; it fails only
on size.

Open, ranked in `docs/15-super-optimization.md`: fold the 170 B of code fields into header bits,
register-resident VM, 2-byte dispatch table, asm dispatcher, extend the table kernel, audit `main`,
share the tokeniser, flatten the scheduler, reserved base register, cold-bucket primitives.
