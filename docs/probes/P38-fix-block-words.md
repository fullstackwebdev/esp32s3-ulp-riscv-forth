# P38 — Fix the three bugs and prove the block layer

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P37 (the three named bugs) |
| Blocks | G2 — porting the engine. Nothing may be ported on top of known-broken words |
| Serves | R1, R5 |

## Question

P37 named three Forth-layer bugs and one placement bug. Fix them and prove the result the way this project
requires: by execution, with predictions computed outside the VM.

| # | Bug | Fix |
| --- | --- | --- |
| 1 | `IF`/`ELSE` emit the branch **token** with `,` (4 bytes, 4-aligned) where the 16-bit engine reads a **2-byte** operand | emit with `W,`; verify by disassembling/reading back the compiled body, not by "it seems to work" |
| 2 | `BLOCK`: `0= IF DROP 0 BLKDRT ! EXIT THEN` drops the buffer address instead of the status | correct the stack order; `BLOCK` must leave exactly one address, or abort with a name |
| 3 | `SAVE` loses its status the same way | same |
| 4 | the 512 B buffer can overlap the dictionary (P33: buffer at 1792, dictionary at 1842) | place the buffer above the dictionary high-water mark and **assert at boot** with a named error if they overlap |

## Why it matters

Every later step — tasks, documents, the port — sits on these words. A branch that reads a `0x0000` hole as
`DOCOL` produces a stack trace that looks like runaway recursion, which is the most expensive kind of bug to chase
hours later on a chip with no debugger.

## Given — do not re-derive

* P37: bug 1 traced to `rsp` climbing 2,3,4… from a `0x0000` hole executed as `DOCOL` at address 0. Bugs 2/3 are
  stack-order slips around `0=` (TOS-only).
* P33: block layer **456 B**; buffer 512 B inside `mem[]`; protocol 4/4; `ERR_NO_SERVER` reachable at four polls.
* P36: app space **620 B**; dictionary ladder measured.
* P20/P28: 16-bit tokens; `,` = `a4()` + 4 bytes, `W,` = 2 bytes.

## Method

1. Copy the P33 tree into `probe/results/P38-fix-block-words/`.
2. Apply the four fixes. **One commit-sized change each**, so a regression is attributable.
3. Prove, each against a prediction computed on the host:
   - **(a)** a compiled `IF … ELSE … THEN` and a `BEGIN … UNTIL` produce the expected values across four
     nesting levels;
   - **(b)** read back a compiled branch body and show the operand is **2 bytes** and points at the target (print
     the token stream, do not eyeball);
   - **(c)** `BLOCK` returns exactly one address; a call with a bad block leaves `sp` unchanged and aborts with
     `ERR_RANGE`;
   - **(d)** `SAVE` returns its status; a failed save leaves `sp` unchanged;
   - **(e)** the buffer assertion fires with a named error when the dictionary is artificially grown into it.
4. Re-run the **58-test suite** and P33's four execution cases.
5. Report the Forth layer's size after the fixes (it should change by a few bytes only) and the buffer's placement.

## Record

| Item | Value |
| --- | --- |
| (a) compiled conditionals, 4 levels | pass/fail |
| (b) branch operand size and target | bytes, address |
| (c) `BLOCK` stack discipline | pass/fail |
| (d) `SAVE` status | pass/fail |
| (e) overlap assertion fires | pass/fail, error name |
| suite | must be 58/58 |
| block layer size after fixes | bytes |

## Pass criteria

* every one of (a)–(e) passes against a stated prediction;
* the branch operand is proven 2 bytes by reading the token stream;
* the suite stays green and the layer's size barely moves.

## Failure criteria — and what each changes

* **(b) fails** ⇒ the emitter is still wrong somewhere else (`LIT` operands? `(.")` strings?); report every place a
  width is written and which one is wrong.
* **(c)/(d) need a redesign** ⇒ say so; a block word that cannot guarantee its stack effect is not usable and the
  layer needs a different shape (a status variable instead of a return value).
* **(e) cannot be asserted in Forth** ⇒ it must be asserted in the C build (a link-time or boot-time check), and
  that is a finding about where safety lives.
* **Suite regression** ⇒ `FAIL`, and the failing word named.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.5 — block layer: fixed, with the measured size.
* `docs/JOURNAL.md` — the fix and the width rule, so nobody writes `,` for a 16-bit operand again.
* `docs/02-harness.md` — if the overlap assertion belongs in the boot path, say where.

## Do not

* Do not "fix" a bug by changing the test.
* Do not port anything to the chip in this probe.
* Do not touch the board, `docs/`, or other probes' directories.
