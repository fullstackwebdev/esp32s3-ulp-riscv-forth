# 17 — Prediction ledger

**Rule: the prediction is written here BEFORE the probe runs, and the result is appended beside it without editing
the prediction.** A prediction made after the fact is a story, not evidence. If a probe's outcome is not in the
prediction list, the probe was not designed to separate anything and its result is not a finding.

Format: `Pn | hypothesis | prediction | RESULT`.

---

## P1 — host trace of the exact phase bytes

Not yet run. Predicted outcomes, in the order they will be checked:

1. `refusal counter > 0` ⇒ a definition was refused ⇒ P4 (rename) next, and the engine's hash/check is the suspect.
2. `counter = 0` and the token ring shows a **truncated or merged** token ⇒ boundary damage ⇒ P2c next.
3. `counter = 0`, tokens correct, first token reaches `vm_enter` ⇒ content ⇒ P5 bisect next.
4. `counter = 0`, tokens correct, first token never reaches `vm_enter` ⇒ the block is not being fed to the
   interpreter at all ⇒ loader/`word()` fault.

## P2 — instrument verification

Predict 4 096 (block 0 = 128 spaces) and 8 320 (block 1 = 128 `A`). Anything else ⇒ the instrument is broken, and no
other measurement in this plan is valid until it prints those two numbers.

## P2b — transport verified before execution

Predict **all 56 segments match** for the 7 phase blocks (the seeder blanks and writes, and the store round trip was
already proven at 16 KB with 0 mismatches). If a mismatch appears, predict it is on a **retried** seed, i.e. a block
whose first attempt was lost and whose second attempt took the non-blanking path.

## P2c — padding and boundary

Predict probe **a** (`: ZZ 42 . ;` + 116 spaces) **passes**: spaces are whitespace, the chunker cuts back to a space,
and the earlier 2-block proof used a padded block. If it *fails*, the padding added to `seed_poll` is the trigger and
that is the cheapest possible repro in the plan.

Predict probe **c** (text ending exactly at byte 128, no trailing space) **passes** — the chunker cuts at a space, so
a 128-byte block whose last token ends at the boundary is the same shape as probe a.

## P3 — device per-block confirmation

Predict `LATEST` **stays frozen for block 8** (it did in the last run: 1436 before and after every block) and `HERE`
creeps. If P1 reports correct tokens, predict `' DATABLK` answers `DATABLK?` even though block 8 contains
`4 CONSTANT DATABLK` — i.e. the definition never took effect.

## P5 — content bisect

Predict the 16 B prefix `4 CONSTANT DATABLK` **succeeds in isolation** (it did: LATEST 1478, `' DATABLK` = 794) and
that the failure appears only once the prefix is long enough to reach the `CREATE … ,` chain or the boundary.

## P6 — length ladder

Predict the first failing length is **2 or 3** blocks, because `8 LOAD` failed earlier with `DATABLK?` — the first
block already fails on its own content, so the ladder should stop immediately. If instead 2–6 pass and only 7 fails,
the fault is cumulative and points at the dictionary window (`ERR_DICT`) rather than at content — and that would be a
very different, and much better, problem.

---

## Results (appended, predictions above never edited)

_(none yet)_
