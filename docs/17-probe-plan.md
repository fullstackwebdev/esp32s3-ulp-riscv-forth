# 17 — Probe plan: the 7-block phase

Each probe states **what it separates**, the **exact commands**, and **predictions per hypothesis**, so a result
cannot be read as confirming the thing I hoped for. Board hard-reset before every device probe. One command per line.
Free (host/offline) probes come first — they cost nothing and can name the fault directly.

---

## Facts already settled (do not re-litigate)

| fact | evidence |
|---|---|
| `err()` prints **PAD**, the last parsed token, and `mkentry`'s refusal path calls the same `err()` | `src/uforth.c:565`, `811-850` |
| ⇒ a **refusal and a not-found are indistinguishable by message**; only `LATEST`/`HERE` deltas differ | both leave `HERE`/`LATEST` unmoved |
| `WHILE`/`REPEAT` are standard (`(0BR)` / `BRANCH`) | `src/p39_prelude.fs:61-67` |
| none of `DATABLK tw idx z1 TAB S1 SHOW` is resident | `' NAME` → `NAME?` on a reset board |
| `CREATE`/`CONSTANT`/`:` all work at the prompt **and from a block**, before and after `SEAL` | LATEST 1481→1466, xts 794/800/808/814/820/828 |
| a definition **split across two blocks** works | `CREATE VU` in one block, `0 ,` in the next |
| a refusal prints `NAME?` with `LATEST` frozen | `: CREATE WW 0 ,` → `CREATE?`, LATEST unmoved |
| **parse the echo out**: a command line containing digits puts them in the transcript | `... 16 < WHILE ...` returned "16" and looked like a checksum |

## Instrument rules (a measurement is void until it passes these)

1. **Never parse a number out of a line that contained one.** Push on one line, print on the next: `8 BLOCK 16 +`
   then `S16 .` — the second line's echo has no digits, so the only number in the reply is the result.
2. **Verify the instrument against known content before use.** Block 0 is all spaces ⇒ sum 4 096. Seed block 1 with
   128 `A`s ⇒ sum 8 320. If it does not print those, the instrument is broken, not the target.
3. **Board reset at the start of every probe** (`esptool --after hard_reset chip_id`). Otherwise the previous probe's
   `SEAL`ed, rewound dictionary is still in RAM.
4. **Print full transcripts**, not tails. `_STACK` was unreadable for three rounds.

---

## P1 — Reproduce the exact phase bytes on the HOST with a traced interpreter (free, do first)

**Separates:** *where* the failure is, and whether it is a refusal at all.

Host build of the same engine already runs phases (`tests/capacity.sh`), so the phase's **exact chunked bytes** can be
played without a chip. Build the host binary with a `-DHOST` trace (dev-only, zero ULP bytes) that prints, for every
interpreted token: the token text, `HERE`, `LATEST`, and whether `find()` succeeded; plus a counter incremented inside
`mkentry`'s refusal branch so refusals are **counted, not inferred**.

Predictions:

| hypothesis | `LATEST` after block 8 | refusal counter | trace shows |
|---|---|---|---|
| a definition refused | moved then rewound (never advances) | **> 0** | `mkentry` refusing, naming the name |
| a token not found | unmoved | 0 | `find()` failing on `DATABLK` with a *correct* PAD |
| `CREATE`/`CONSTANT` never executed | unmoved | 0 | the block's first token never reaches `vm_enter` |
| boundary/parse damage | unmoved, `HERE` creeping | 0 | a token whose text is **truncated or merged** with its neighbour |

**The refusal counter is the discriminator the message cannot be.** This probe alone may name the fault.

## P2 — Instrument verification (host, free)

Seed block 0 (all spaces ⇒ 4 096) and block 1 (128 `A` ⇒ 8 320); assert the checksum prints those two numbers via the
push/print split. Predictions: 4 096 and 8 320 ⇒ instrument good; anything else ⇒ instrument broken, stop and fix it.

## P3 — Confirm on the device with the per-block protocol (cheap)

Only after P1 says something: reset; seed the phase's 7 blocks; `SEAL`; `2 OVL`; then for each block **one line**
`N LOAD`, then `LATEST .` and `HERE .` each on its own line, plus `' <NAME-FROM-THAT-BLOCK> .` for the name the block
should have defined.

Predictions: if P1 found a refusal, `LATEST` stays frozen for every block **and** `' NAME` answers `NAME?`; if P1
found a parse problem, the block that fails is the one whose *boundary* is wrong, so blocks before it will have moved
`LATEST` and defined their names. **A block that moves `LATEST` and defines its own name but errors later is a
different fault from one that defines nothing.**

## P4 — Hypothesis 5: rename, then load (device, cheap) — only if P1/P3 suggests a refusal

Rename every definition inside the phase (`DATABLK→DBLKX`, `tw→TWX`, `idx→IDXX`, `z1..z6→ZAX..ZFX`, `TAB→TABX`) so no
name could possibly match a resident header, re-chunk, re-seed, load.

Predictions: failures vanish ⇒ **name-related**, and the engine's hash is wrong somewhere (print the computed hash and
the resident header it matched). Failures identical ⇒ **not name-related**; go to P5.

## P5 — Content bisect inside one block (device, cheap)

Take the phase's block 8 text (128 B) and load successively shorter **prefixes, cut at spaces**: 128 → 64 → 32 → 16 B.
Each prefix in its own block, fresh reset per length.

Predictions: the first length that succeeds bounds the fault to a few tokens, and the last failing prefix names the
token. If even the 16 B prefix `4 CONSTANT DATABLK` fails *in this context* while the same text in a 19 B block
succeeded earlier, the trigger is **position/context, not content** — so also seed that same 19 B text into block 8
at the phase's offsets (empty blocks around it) to separate the two.

## P6 — Sequence: content vs position (device, cheap)

Load only blocks 8 then 9; then only 8 then 10; then 9 then 8 (wrong order, expect failure).

Predictions: if `8 → 9` fails, the fault is in the pair (a boundary between exactly those two texts). If `8 → 10`
succeeds, block 9's content is the trigger. If both fail, block 8's own text is the trigger, and P5 applies.

## P7 — Make the finding permanent (suite, free)

Whatever P1–P6 names becomes a test that **fails without the fix and passes with it**:

- if a refusal: a test asserting `LATEST` moved after a definition that must succeed;
- if a boundary: a test loading a definition split across two blocks, asserting the name resolves;
- if a `CREATE` path: a test seeding `CREATE VV 0 ,` into a block, loading it, asserting `' VV` resolves;
- plus a **deliberate-failure** check for `tests/device_ceiling.py` (`--skip-block`) proving the harness reports it.

`tests/overlay.fs` keeps the green 2-block case as a regression so a fix for 7 blocks cannot silently break it.

---

## Time-box and fallback

Two probes (P1, P3) or roughly one session. If neither names the fault, the record says **"device verified to 2 blocks
and to block-source definitions"** and the next work is the clock and the compiler-removal decision — both of which
lower the toll for every later result, and neither depends on this bug.
