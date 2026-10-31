# P22 — Does the machine, as now specified, fit?

| | |
| --- | --- |
| Runs on | **host only** (build + link) |
| Time box | **15 min**, one run, hard cap |
| Depends on | P13, P19, P20, P21, P12 |
| Blocks | the whole §4.3 budget; whether Forth work can start |
| Serves | R1, R5 |

## Question

Every line of §4.3 has now been measured separately. Nobody has built the machine they add up to. Does
it **link**, and how much dictionary does it actually leave?

Build exactly this and report the numbers:

| Line | Value | Source |
| --- | --- | --- |
| engine | 40-primitive set | P20 variant C (3162 B) |
| code references | **32-bit xts** | P02/P12 (16-bit deferred) |
| page frames | 4 × 512 B | P03f, P19 |
| page table + LRU | 4 slots | — |
| Forth stacks | 128 B (20 data + 7 return cells, plus margin) | P13 |
| mailbox + rings | 384 B rings + mailbox | P04 |
| C stack | 320 B | P21 |
| line buffer | 128 B | P10 |
| dictionary | **headerless resident** + paged name directory | §4.3 resolution A |

## Why it matters

This is the "does it fit" question, and it has been answered wrong twice already: once when the engine
was estimated at 2600 and measured 3818, once when the frames were assumed to be 1024 and measured 2048.
The only trustworthy answer is a link.

## Given — do not re-derive

* `probe/results/P20-native-accessors/` variant C is the engine to use, with its 40-primitive table.
* `probe/results/P12-engine-32bit/` has the paging-enabled build recipe and stub-subtraction technique.
* P20 variant D measured the prelude's dictionary at **1716 B with headers**. Resolution A moves ~44 %
  of that out, so the resident need is **~962 B**.
* Headroom with all the lines above: **1518 B**.
* `mem[]` is `.bss`, so it does not inflate `.bin`; `MEMSZ` must be chosen as *whatever is left*.

## Method

1. Copy P20's variant C tree into `probe/results/P22-fits/`.
2. Apply the remaining §4.3 decisions: frames 4 × 512 B + 4-slot table, Forth stacks 128 B, C stack
   320 B (`-Wl,--defsym` or the linker script's `__stack_top` offset), line buffer 128 B, and the
   headerless name-directory split (names+links moved out of the resident dictionary into a separate
   array that would live in paged storage; the resident area keeps code fields and bodies).
3. Compile the prelude, then **move the headers out** and report: resident dictionary bytes, directory
   bytes, and the total Forth memory actually needed.
4. Set `MEMSZ` to `8176 − (engine + frames + table + stacks + rings + C stack + line buffer)` and
   build. Report whether the link succeeds; if it fails, the exact message.
5. Report the final image: `.text`, `.rodata`, `.bin`, `.bss`, and the leftover bytes.

## Record

| Item | Value |
| --- | --- |
| engine `.text` / total | |
| resident dictionary after headers move | |
| name directory size | |
| `MEMSZ` chosen | |
| link result | pass / fail + message |
| `.bin` | |
| **leftover bytes** | |

## Pass criteria

* the image **links** with all §4.3 lines at their measured values;
* resident dictionary and directory measured, not extrapolated;
* leftover bytes stated as a number.

## Failure criteria — and what each changes

* **Link fails** ⇒ report the exact overrun. §4.3 is then wrong again and the difference must come from a
  named line, not from trimming the prelude quietly.
* **Resident dictionary > 1518 B even headerless** ⇒ resolution A is insufficient at 32-bit; the choices
  become 16-bit code tokens (P02: −1.49×) or a smaller prelude. That is a design decision, not a probe.
* **Links with < 100 B leftover** ⇒ report it as "fits, no room to grow" — the next feature will not fit
  and the plan must say so.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.3 — the final table, with the linked numbers replacing every estimate.
* `docs/01-proposal.md` §10 — R1's engine item, if the link proves it.

## Do not

* Do not shrink the prelude, drop words, or change the primitive set to make it link. Report the overrun.
* Do not touch the board, `docs/`, or other probes' directories.
