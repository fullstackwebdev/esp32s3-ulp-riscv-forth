# P10 — REPL line discipline, escape framing and flow control (host)

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P04 (rings, `k=4`, `repl_step`) |
| Blocks | R8 acceptance items 2–4 and 8 |
| Serves | R8 |

## Question

With a **dumb terminal on the other end** — no framing, no pacing, bytes arriving whenever the OS
feels like it — does the console path behave correctly, and does the reserved escape byte stay
harmless in real Forth source?

Specifically: line discipline (`CR`/`LF`/`BS`/`DEL`/garbage/over-long), the `0x1D` escape table
(`0x1D 0x1D`, `0x1D f`, `0x1D p`, `0x1D s`, `0x1D q`, unknown), and XOFF behaviour when the command
ring fills. The false-positive question is the one that decides whether `0x1D` is a safe escape:
count how often it occurs in real Forth source.

## Given — measured already, do not re-derive

* Rings: **cmd 128 B, out 256 B**, `k = 4` tokens per `repl_step`, 4 steps per wake (P04).
* `KEY` on an empty ring returns `ERR_NO_INPUT` and consumes nothing (P04).
* `repl_step(k, nchars)` returns `MORE | LINE_DONE | ERR` and keeps its cursor in memory (P04).
* Host suite baseline is **58/58** in `probe/uforth/` (`host_test.c`), including the `BASE`/`HEX`
  regression tests. Your changes must keep it green.

## Method

1. Copy `probe/uforth/` into `probe/results/P10-repl-host/` and work there.
2. Implement the **bridge model** on the host: a byte source feeding `cmd[128]`, a byte sink draining
   `out[256]`, the escape state machine with exactly **one byte of lookahead**, and the XOFF rule at
   75 % occupancy. Keep it separable from the interpreter so the tests can drive bytes directly.
3. **Escape false-positive rate.** Scan every `.fs` file in the repo plus a synthetic corpus of
   ~2000 lines written in the style of `boot_min.fs`; count `0x1D` occurrences. Report count, rate per
   kilobyte, and the lines if any. This decides whether the escape is safe as designed.
4. **Escape table.** For each sequence, assert the documented behaviour:
   - `0x1D 0x1D` → one literal `0x1D` reaches the ULP input buffer;
   - `0x1D f` / `0x1D p` → mode flips, nothing reaches the ULP buffer;
   - `0x1D s` → exactly one ASCII state line out, no change to the console stream;
   - `0x1D` followed by `x` (unknown) → **both bytes** reach the buffer verbatim;
   - `0x1D` at the end of a burst → flushed as a literal after a bounded timeout (state the bound).
5. **Line discipline table**, driven byte by byte: printable, `BS`, `DEL`, `CR`, `LF`, control bytes
   (ignored and counted), 129-byte line (`ERR_LINE_TOO_LONG`, line dropped, dictionary byte-identical
   — verify `HERE`/`LATEST` unchanged), and a line split across two ring refills.
6. **XOFF**: fill `cmd` past 75 % and confirm the bridge stops accepting, reports `XOFF`, and resumes
   without losing a byte once the ULP drains. Then assert it never drops silently.
7. **No double echo**: with host echo off, the bytes out must equal exactly what the ULP echoed — no
   line appears twice.

## Record

| Item | Value |
| --- | --- |
| `0x1D` occurrences in real + synthetic corpus | count, per KB |
| escape table: sequences correct | n / 6 |
| line discipline: cases correct | n / 7 |
| XOFF round trip | bytes lost (must be 0) |
| double echo | none / observed |
| suite | must stay 58/58 |

## Pass criteria

* every escape and line-discipline case behaves as `06-repl.md` §3–§4 states;
* XOFF loses nothing;
* no double echo;
* suite 58/58.

## Failure criteria — and what each changes

* **`0x1D` appears in real source more than once per 10 KB** ⇒ it is not a safe escape; switch to a
  longer sequence (e.g. `0x1D` preceded by nothing but at line start), and say so — `06-repl.md` §3
  changes.
* **Unknown escape eats bytes** ⇒ the one-byte lookahead rule is wrong; the escape must be
  recognise-or-pass-through with no consumption on a miss.
* **XOFF loses a byte at the boundary** ⇒ the ring needs a real credit scheme, not an occupancy
  threshold; `06-repl.md` §5 changes.
* **Double echo** ⇒ the host echo assumption is wrong somewhere; report which side echoed twice.

## Doc deltas to hand back

* `docs/06-repl.md` §3 (escape table), §4 (line discipline), §5 (flow control) — corrected to what was
  measured, including the false-positive rate.
* `docs/01-proposal.md` §10 R8 items 4, 5, 8 — restated with the measured numbers.

## Do not

* Do not touch the board; another probe owns it.
* Do not measure latency — that is P11's job on the real link.
* Do not edit `docs/` or `probe/uforth/`.
