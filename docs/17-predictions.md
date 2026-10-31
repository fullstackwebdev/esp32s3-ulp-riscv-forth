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

### Session A — device, 2025 run (all five predicted PASS, all five PASSED)

| probe | prediction | result |
|---|---|---|
| P2c-a `: ZZ 42 . ;` padded to a full block | ok, `' ZZ` resolves | **ok, `' ZZ` = 794** ✓ |
| P2c-b `4 CONSTANT QP` padded | ok, `' QP` resolves | **ok, `' QP` = 794** ✓ |
| P2c-c 128 B ending on a token, no trailing space | 42 printed, ok | **`42` printed, ok, `' ZC` = 794** ✓ |
| P2c-d block ends on a bare name `CREATE ZT` | ok, `' ZT` resolves | **ok, `' ZT` = 794** ✓ |
| P2c-e 7 blocks, ONE definition each | all ok, `' E7` resolves | **all 7 ok, LATEST 1481→1463, `' E1` 794, `' E7` 854** ✓ |

Consequence: **padding is not the trigger, a token ending at byte 128 is not the trigger, a block ending on a bare name
is not the trigger, and seven blocks in sequence is not the trigger.** The only shape still untested is a **colon body
that spans a block boundary** (`: S1 … REPEAT` closed by `;` at the start of the next block), and the `CREATE … ,`
chain that a boundary cuts in half. New probe P2c-f added for exactly that.

### Session B — instruments, transport, and the traced host run

| probe | prediction | result |
|---|---|---|
| P2 verify checksum instrument | 4 096 and 8 320 | **INSTRUMENT ABANDONED**: `DEPTH` and `DO/LOOP` do not exist on this machine (`DEPTH?`, `DO?`), and two `BEGIN/WHILE/REPEAT` attempts printed the loop counter. Replaced by a `C@`-at-known-offset readback, which needs no loop and cannot be misparsed. |
| P2b transport before execution | all segments match | **72/72 byte checks MATCH** over 9 seeded blocks (offsets 0,1,2,3,64,120,126,127), including the last two bytes. Seeder and store are out of the suspect list permanently. |
| P3 per-block, with names | `LATEST` frozen at block 8 | **refuted, and it mattered**: after a hard reset block 8 loads `ok` and `' DATABLK` resolves (794). The earlier "frozen from block 8" reading came from a board that had NOT been reset — the lesson is now a GUARDRAIL in `device_ceiling.py`. |
| P4 rename (only if a refusal) | failures vanish if name-related | **not name-related**: `CREATE QQ/QP/ZT/VV/TWX/IDXX/Z4` all succeed at the prompt and from blocks, before and after `SEAL`; the host refusal counter reads **0** for the whole phase. |
| P5 content bisect | 16 B prefix succeeds in isolation | **size, not content, is the trigger**: 128 B blocks lose their final token, 120 B mostly survive, ≤92 B is safe by construction (one tib pass). |
| P6 length ladder | first failing length 2–3 | **refuted**: 2 blocks green, 7 blocks one-definition-each green (LATEST 1481→1463, `' E7`=854), and an 8-block phase green apart from the tail-loss blocks. Length is not the fault; a definition spanning a **tib pass** is. |
| P1 traced host run | a refusal, a truncated token, or correct tokens | **none of the four**: `refusals=0`, tokens correct, and the state dump showed `STATE=1` at end-of-source with `10`/`LOAD` read at `ST=1` and the stray `;` arriving afterwards. That is a fifth outcome the table did not list — a **leftover tail delivered after the next line started**. |

### P1b decision (recorded, per the plan's decision tree)

Counter = 0 and no truncated token, so neither P4 nor a parse fault. The trace named a **block/tib pass boundary**
fault, so the fix went to the splitter (`tools/fsplit.py`) with its own failing selftest, and the engine-side guard was
written, measured to conflict with an existing intentional-refusal test, and withdrawn with the reason recorded at the
site in `interpret()`.

### Session C — the items that had been closed by argument, now executed

| probe | prediction | result |
|---|---|---|
| **P1 counter validation** (deliberate failure) | the refusal counter must be able to fire, or `refusals=0` means nothing | **`SEAL` then `: CREATE WW 0 ,` on the host ⇒ `[P1 REFUSE] … refusals=1`.** The phase run then reports `refusals=0`. So the counter is proven able to count, and P1's zero is evidence rather than an untested assumption. |
| **P2 instrument verified against known content** | spaces ⇒ 32, `A` ⇒ 65, and a deliberate mismatch must be detected | **PASS**: block seeded with 128 spaces reads `32,32,32` at offsets 0/64/127; 128 `A`s read `65,65,65`; a block with one `B` at offset 64 reads **66** where 65 was wanted — **the instrument can fail.** (First attempt read `0,0,0` because `BLKBLANK` is bound to block 0's window: my probe was wrong, not the machine.) |
| **P5 content bisect 127/64/32/16** | short prefixes succeed, the truncation point is where it breaks | **127 B ⇒ ok (LATEST −18), 64 B ⇒ ok (−12), 32 B ⇒ ok (−6), 16 B ⇒ `?`, LATEST −0.** The 16 B prefix is `4 CONSTANT DATABL…` cut inside a token, so the failure is an incomplete token, not a size effect — the bisect bounds it precisely. |
| **P6 length ladder 2..7 + content swap** | first failing length 2–3 | **first failing length is 5**: 2 ⇒ 130 B ok, 3 ⇒ 132 B ok, 4 ⇒ 184 B ok, 5,6,7 ⇒ 184 B with `12 LOAD → Z4?`. **Content swap** (slot 10 carrying block 14's text) still fails at **block 12** ⇒ the fault tracks the *slot*, not that block's content — consistent with blocks 8/9 (127 B, 128 B, i.e. longer than one 96-byte tib pass) poisoning the load, and block 12 being the first block that *uses* the lost definitions. |
| **P7 the defect as a probe** | a registered probe that states the correct behaviour | **`tests/known_defect_tail.fs`** — a 97 B definition whose `;` sits at offset 96 — answers `TAILTEST?` today. `tools/known_defects.sh` reports **`DEFECT F-BLK-TAIL: want '42', got ':?TAILTEST?'`**, so a fix prints FIXED and the probe is promoted instead of a golden file being written around the gap. |
| **P3b chip refusal counter** | only if P1 is ambiguous | **not required, and that is now evidence-backed**: P1 is unambiguous (STATE=1 with a leftover tail) and the host counter was shown to fire. No chip counter was built, because the question it would answer is already settled. |
