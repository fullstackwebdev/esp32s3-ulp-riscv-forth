# P20 — What do native accessors and a trimmed primitive set buy?

| | |
| --- | --- |
| Runs on | **host only** (build + disassemble) |
| Time box | **15 min**, one run, hard cap |
| Depends on | P14 (dispatch = 1 074 cycles), P12 (engine 3986 B) |
| Blocks | the engine line and the dispatch budget in §4.3/§5; the whole "does it fit and is it fast" question |
| Serves | R1, R3 |

## Question

P14 measured **90.9 %** of a dispatch as `NEXT` + dispatch head, dominated by **two byte-wise `rd32`
fetches at 452 cycles each**. Two changes have never been measured together:

1. **native `lw`/`sw` accessors** for 4-aligned cells (D7) — how much does dispatch cost fall, and does
   the engine get **smaller** or larger?
2. **trimming the primitive set** from 64 entries to the ~40 that the design actually needs — how many
   bytes of dictionary and engine does that recover?

## Why it matters

§4.3 is **482 B short** and §8's typing latency (226 µs per 4-token slice) is a consequence of an
avoidable cost. If native accessors both speed it up *and* shrink the engine, one change closes two
problems. If they grow the engine, the trade must be stated.

## Given — do not re-derive

* P14: dispatch 1 074 cycles typical; `NEXT` 480; dispatch head 496; `rd32` 452 (byte-wise, 8 × `lb`);
  native `lw` path measured at 8.1 cycles + instrumentation (P05).
* P12: engine 3986 B = `.text` 3734 + `.rodata` 252 at 32-bit refs + paging.
* P01's build recipe and stub-subtraction technique (`probe/results/P01-engine-size/`).
* P02's 32-bit `uforth.c` (`probe/results/P02-token-width/`); P12's paging-enabled copy
  (`probe/results/P12-engine-32bit/`).

## Method

Build **four variants** from P12's source and measure each. Keep every other difference out.

| Variant | Change |
| --- | --- |
| **A** | baseline (P12's engine, byte-wise accessors) — must reproduce 3986 B |
| **B** | `rd32`/`wr32` on 4-aligned addresses use native `lw`/`sw`; unaligned falls back |
| **C** | B + primitive set trimmed to the ~40 essential entries (drop `W@`, `W!`, `U/MOD`, `ROT`, `NIP`, `TUCK`, `KEY?`, `MS`, and the debugging extras; keep everything §4.2's list names) |
| **D** | C + the prelude's 36 words compiled in, to check the dictionary figure with the trimmed set |

For B/C/D report `.text`, `.rodata`, `.bin`, and the dictionary bytes for the same prelude. Then re-run
P14's accounting on variant **C** (the one that would ship) and report dispatch cycles best/typical/worst.

## Record

| Variant | engine `.text` | engine total | dictionary for the prelude | dispatch cycles |
| --- | --- | --- | --- | --- |
| A baseline | | | | 1 074 |
| B native accessors | | | | |
| C + trimmed primitives | | | | |
| D + prelude resident | | | | |

Plus: the three consequences re-stated in ticks and µs for variant C (typing slice, prelude line,
505-dispatch token).

## Pass criteria

* variant A reproduces P12's 3986 B (otherwise the comparison is invalid);
* B/C/D measured with the same recipe, stub subtracted;
* dispatch cycles recomputed for C from the disassembly, not estimated.

## Failure criteria — and what each changes

* **Native accessors grow the engine** ⇒ state the cost; D7 becomes a speed-for-space trade and §4.3
  must account for it.
* **Trimming recovers < 200 B** ⇒ the primitive set is not the lever it looked like; §4.3 must find its
  482 B in the prelude or the frames instead.
* **Dispatch still > 400 cycles in C** ⇒ `NEXT`'s two-fetch design is the problem, not the accessor.
  Then the fix is to cache the resolved code-field pointer per token class — a different change, and
  worth naming as the next question.
* **Variant D does not fit** in 8176 − frames ⇒ report the overrun; that is the machine, measured.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.3 — engine and dictionary lines from variant C/D.
* `docs/01-proposal.md` §5 and §8 — dispatch cycles and the connected period.
* `docs/03-prototype-review.md` D7 — resolved: measured effect on both size and speed.
* `probe/EVIDENCE.md` — extend E-021/E-023.

## Do not

* Do not change the retry mechanism, the token width, or the frame layout — those are decided.
* Do not touch the board, `docs/`, or other probes' directories.
