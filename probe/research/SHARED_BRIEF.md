# SHARED BRIEF — P54 lever probes (read this before your TASK.md)

## Context you must not re-derive (already measured)
Shipping image: pool **7 853 / 7 856 B**; `.text` **5 252**, `.rodata` **308**, `.data` **1 416**, `.bss` **877**;
`MEMSZ` **1 400**; `BLKADR` **1 272**; app space **354 B**; **85** dictionary words; **64** primitive bodies at a
measured **29.5 B** each; `vm_enter` = **2 782 B** (53 % of `.text`); recursion depth 15; 2 task slots.

App space is `V_LATEST − V_HERE`, both inside `mem[]`. So **every byte removed from `.text`/`.bss` becomes one
byte of application space** — but only after a re-bake at the raised `MEMSZ` (`tools/bake.sh <MEMSZ>` owns that).

## Hard rules
- **Never** touch `/dev/ttyACM*`, never flash, never run `idf.py`. Host/compiler work only.
- Do not modify anything outside your own directory. Never write into `probe/repl/build`.
- No `/tmp`, no `find /` or `$HOME` scans, no background `&`, `timeout` every command, `nice -n 15` for builds.
- Every code edit needs `// GUARDRAIL: <lesson> — <reason> — <fix>` on the changed lines.
- **Fail loud.** No silent defaults, no placeholder values, no mocks, no placeholder calls.

## Method: the twin build (`./measure.sh`, written by agentA)
It compiles a variant with the **shipping** ULP flags and **shipping** link line, and proves the baseline
reproduces the shipping image's `.text` **sha256** before any delta is quoted. Adapt it to compile `src/` in
your own directory. **If the baseline sha256 self-check fails, STOP and report the failure** — a delta from an
unverified twin is not a measurement. Compare with `riscv32-esp-elf-size -A` and `nm -S --size-sort`.

## Acceptance for a "win"
1. baseline twin reproduces the shipping `.text`;
2. `tests/run.sh` green on the variant (new tests must be **mutation-tested**: break it, watch it fail, restore);
3. the delta is **measured** from ELF sections/objdump, never estimated;
4. say plainly what it costs (dispatches, complexity, risk), including "cannot be measured on the host".

A well-measured **negative** is a first-class result. Do not round a failure up into a smaller win.

## Deliverable
`FINDINGS.md` in your directory: method, measured variants table (`variant → Δ.text → Δ.rodata → Δ.bss → suite`),
verdict, the exact diff of any winner, and the list of what you could not measure.
