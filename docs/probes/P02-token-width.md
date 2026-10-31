# P02 — Token width: 16-bit vs 32-bit xt, density and page fit

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P01 (engine size, for context only) |
| Blocks | P03, `01-proposal.md` §7 last bullet |
| Serves | R1, R5 (one definition per page) |

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

What does moving from 16-bit tokens to 32-bit virtual xts cost in dictionary density, and how often
does a real definition straddle a 512 B page boundary under each scheme?

## Why it matters

R5 needs a data space larger than 64 KB, which 16-bit tokens cannot index. §7 accepts "~30 bytes per
word instead of 21" as the price. That is an estimate. Worse, the *page-straddle rate* decides
whether "one definition per page" is a mild discipline or a constant irritation — if 20 % of
definitions need a page boundary check, the compiler gets more complex and users hit
`ERR_WORD_TOO_BIG` regularly.

## Method

1. Copy `probe/uforth/` into `probe/results/P02-token-width/` and work there.
2. Two builds of the same source:
   - **A. 16-bit tokens** — the current baseline (`rd16(ip)`, `cw()` appends 2 bytes).
   - **B. 32-bit xts** — `cw`/`clit`/`find`/branch operands widened to 4 bytes, `ip` as `u32`.
     Keep everything else identical; this is a width change, not a redesign.
3. For each build, compile the same corpus with `boot_min.fs` plus a few larger definitions
   (include one word of ~20 tokens and one with several string literals):
   - total dictionary bytes and words emitted;
   - **bytes per word**, mean and maximum;
   - number of definitions whose body exceeds 512 B (would be refused under the page rule);
   - number of definitions that *straddle* a 512 B boundary when packed from a 4-byte-aligned start,
     counted both for "page = 512 B aligned" and "page = 512 B from DICT".
4. Report the same for a 256 B page, so the page-size decision has data behind it.
5. Sanity: both builds must pass `host_test.c` unchanged (53 tests) — a width change that breaks
   behaviour is a bug in the change, not a finding.

## Record

Table: build × {bytes, words, bytes/word mean, bytes/word max, >512 B count, straddles at 512,
straddles at 256}, and the test-suite result for both builds.

## Pass criteria

* both builds pass all 53 tests;
* the density and straddle numbers are produced from a recorded command line.

## Failure criteria — and what each changes

* **Mean > 35 B/word with 32-bit xts** ⇒ §7's estimate was optimistic; report the real number and
  propose either fewer literals (`LIT` + inline operand is the main cost) or a 2-byte "small literal"
  encoding. This is a compiler change, not an architecture change.
* **Straddle rate > 5 % at 512 B** ⇒ the compiler must handle two-page definitions (pin both frames)
  instead of refusing them; `01-proposal.md` §4.2 rule 1 changes.
* **Straddle rate > 10 % at 256 B** ⇒ 256 B pages are dead; keep 512 B.
* **Any test regression** ⇒ `FAIL`: the width change is wrong.

## Doc deltas to hand back

* `docs/01-proposal.md` §7 bullet "References are 32-bit…" — replace "~30 bytes per word" with the
  measured mean.
* `docs/01-proposal.md` §4.2 rule 1 — keep "one definition per page" or replace with the two-page
  rule, depending on the straddle rate.

## Do not

* Do not change page size in the proposal from this probe alone; report numbers, let the orchestrator
  decide.
* Do not touch the board or `docs/`.
