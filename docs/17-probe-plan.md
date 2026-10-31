# 17 — Probe plan: the 7-block phase (v2)

Every probe states **what it separates**, the **exact commands**, and **predictions per hypothesis**, written down
*before* the run in `docs/17-predictions.md` so a result cannot be read as confirming what I hoped for. Free probes
(host/offline) come first because they cost nothing and can name the fault outright.

---

## 0. Protocol upgrades (apply to every probe, non-negotiable)

| rule | why it exists |
|---|---|
| **Prediction ledger** — write the prediction in `docs/17-predictions.md` *before* running, then append the result beside it | a prediction made after the fact is a story, not evidence |
| **One change, then the whole suite** — `tests/run.sh` must be green before and after, with the green 2-block case kept as a regression | a fix for 7 blocks must not silently break 2 |
| **Board hard-reset first** (`esptool --after hard_reset chip_id`) | the previous probe's `SEAL`ed, rewound dictionary otherwise persists — measured |
| **Board reset before each length/rename variant**, not just each session | variants contaminate each other |
| **Never parse a number out of a line that contained one** — push on one line, print on the next | `... 16 < WHILE ...` returned "16" and masqueraded as a checksum |
| **Verify the instrument against known content before use** | block 0 = spaces ⇒ 4 096; block 1 = 128 `A` ⇒ 8 320 |
| **Full transcripts, no tails** | `_STACK` was unreadable for three rounds |
| **Evidence tiers on every claim** (host-measured / device-measured / not measured) | the 6× is host-only until a 7-block phase assembles |
| **A probe that cannot fail is not evidence** — each new harness check gets a deliberate-failure run | the 17×70 B false pass |

---

## Facts already settled (do not re-litigate)

| fact | evidence |
|---|---|
| `err()` prints **PAD**; `mkentry`'s refusal calls the same `err()` | `src/uforth.c:565`, `811-850` |
| ⇒ refusal and not-found are **identical on the wire**; only `LATEST`/`HERE`/a counter separate them | both leave pointers frozen |
| `WHILE`/`REPEAT` are standard (`(0BR)`/`BRANCH`) | `src/p39_prelude.fs:61-67` |
| none of `DATABLK tw idx z1 TAB S1 SHOW` is resident; bake inputs are prelude + overlay + line.fs only | `' NAME` → `NAME?`; `tools/bake.sh:28` |
| `CREATE`/`CONSTANT`/`:` work at the prompt and **from a block**, before and after `SEAL`; a definition split across two blocks works | LATEST 1481→1466; `CREATE VU` + `0 ,` in the next block |
| a refusal prints `NAME?` with `LATEST` frozen | `: CREATE WW 0 ,` → `CREATE?` |

---

## P1 — HOST trace of the exact phase bytes (free, do first)

**Separates:** where it fails, and whether it is a refusal at all.

Build the host engine (`-DHOST`) with a dev-only trace — zero ULP bytes, never in a baked image:

1. per interpreted token: text, `HERE`, `LATEST`, `find()` result;
2. **a counter incremented in `mkentry`'s refusal branch** — the discriminator the message cannot be;
3. **a ring of the last 12 parsed tokens**, dumped from inside `err()` **before the rewind**, with `HERE`, `LATEST`,
   the compile state and the refusal counter at that instant.

Item 3 is the review's "stop errors from erasing the evidence", and it would have named both this bug and the last
one directly.

| hypothesis | `LATEST` after block 8 | refusal counter | trace shows |
|---|---|---|---|
| a definition refused | frozen | **> 0** | `mkentry` refusing, naming the name |
| a token not found | frozen | 0 | `find()` failing with a correct PAD |
| `CREATE` never executed | frozen | 0 | the block's first token never reaches `vm_enter` |
| boundary/parse damage | frozen, `HERE` creeping | 0 | a token **truncated or merged** with its neighbour |

**Decision rule:** counter > 0 ⇒ P4 (rename) next; counter = 0 with a truncated token ⇒ P2c (boundary) next;
counter = 0 with correct tokens ⇒ P5 (content bisect) next.

## P2 — Instrument verification (host, free)

Block 0 = all spaces ⇒ 4 096. Block 1 = 128 `A` ⇒ 8 320. Assert both, via push/print-split. Anything else ⇒ the
instrument is broken; stop and fix it before spending chip time.

## P2b — Transport verified *before* execution (device, cheap) — the review's item 5

Reset, seed all 7 blocks, then **without `SEAL`/`OVL`/`LOAD`** read each block back as 8 segment sums (16 B each) with
the verified instrument and compare against the source bytes on the host.

Predictions: all 56 segments match ⇒ the seeder and the store are out of the suspect list **permanently**; any mismatch
⇒ transport fault, and its position (which segment of which block) points straight at the seeder — including whether a
**retried** seed skipped the blanking (the stale-tail bug on a second path).

## P2c — Padding and boundary probes (device, cheap) — NEW, and high value

The space-padding in `seed_poll` is **new code**, and the phase fails with `LATEST` frozen and `HERE` creeping — the
signature of something being consumed without a header. Test the padding/boundary interaction directly:

| probe | block text | prediction if padding is the trigger | prediction if it is not |
|---|---|---|---|
| a | `: ZZ 42 . ;` + 116 spaces (a full 128 B block, one definition) | `ZZ?` — trailing spaces break the tail | ok, `' ZZ` resolves |
| b | `4 CONSTANT QP` + 111 spaces | `QP?` | ok, `' QP` resolves |
| c | text ending exactly at byte 128 with **no** trailing space | ok | ok |
| d | a block whose last token is a **name** (`CREATE ZT`, no body, no trailing space) | ok — the split-definition case already works | — |
| e | 7 blocks of *single* definitions (one per block) | ok — proves multiple-defs-per-block is not required for failure | fails ⇒ multiple defs per block is the trigger |

Probe **a** is the cheapest possible repro if padding is the cause: one definition, one block, and the fix that made
2 blocks work is the suspect.

## P3 — Confirm on the device with the per-block protocol (cheap)

Reset, seed, `SEAL`, `2 OVL`, then per block: `N LOAD` on its own line, then `LATEST .`, `HERE .` and
`' <NAME-FROM-THAT-BLOCK> .` each on its own line.

Predictions: a block that moves `LATEST` **and** defines its own name but errors later is a **different fault** from
one that defines nothing. Record which, per block — this distinction is what all earlier probes missed, and it also
dates whether `HERE`'s creep is compile space from an unterminated `:` (check the compile state with `0 @ .` =
`V_STATE`: non-zero after a block means the block ended mid-definition).

## P3b — Refusal counter on the chip (optional, debug build, not for keeps)

If P1 is ambiguous, flash a temporary build whose `mkentry` refusal increments a cell that a Forth word can read, and
re-run P3. Costs a few bytes of `.text`; **not a keep** — it is a diagnostic, and the counter is removed after.

## P4 — Rename (device, cheap) — only if a refusal is suggested

Rename every definition in the phase (`DATABLK→DBLKX`, `tw→TWX`, `idx→IDXX`, `z1..z6→ZAX..ZFX`, `TAB→TABX`), re-chunk,
re-seed, load. Predictions: failures vanish ⇒ name-related ⇒ **print the computed hash and the resident header it
matched** (an engine bug in the check). Identical ⇒ not name-related ⇒ P5.

## P5 — Content bisect inside one block (device, cheap)

Block 8's text cut at spaces to 128 → 64 → 32 → 16 B, each in its own block, fresh reset per length. The last failing
prefix names the token. If the 16 B prefix `4 CONSTANT DATABLK` fails *here* while the same text in a 19 B block
succeeded, the trigger is **position/context, not content** — so also place that 19 B text at the phase's offsets with
empty blocks around it.

## P6 — Length ladder and content swap (device, cheap) — the review's "bisect on length"

2 blocks green, 7 failing ⇒ test **3, 4, 5, 6** blocks of the phase text. The first failing length names the block;
then **swap that block's content with a later block's** to separate "the block" from "its position", and swap two
passing blocks to prove position-independence.

## P7 — Permanence: every lesson becomes a test (suite, free)

| lesson | test that fails without the fix |
|---|---|
| blank the block before writing | seed a short text into a block previously holding a longer one; assert the tail is spaces |
| strip both comment kinds | a block containing `\ …` and `( … )` loads and compiles the rest |
| one arm per line | arming twice raises a named error (lands with the loop-test rewrite) |
| errors rewind the dictionary | a test that errors deliberately, then asserts `LATEST` is back at the save point |
| `CREATE` from a block | seed `CREATE VV 0 ,`, load, assert `' VV` resolves |
| definition split across blocks | `CREATE VU` in one block, `0 ,` in the next, assert resolution |
| the ceiling harness can fail | `--skip-block` for each of the 7 blocks in turn, each must be reported |

## P8 — Regression matrix (suite, free)

After **every** probe in this plan: `tests/run.sh` (22 tests) + the 2-block device case. Any change that fixes 7
blocks while breaking 2 is not a fix.

---

## Decision tree

```
P1  --refusal counter > 0--> P4 rename --> (fixed? => P7 test : print hash, engine bug)
    --truncated token------> P2c padding/boundary --> P5 bisect --> P7 test
    --correct tokens, 0-----> P5 bisect --> P6 ladder/swap --> P7 test
    --first token never runs> P2c probe a (padding) --> P5
P2b --any mismatch----------> fix seeder (retry path) --> re-run P2b
    --all match--------------> seeder cleared forever
P2c probe a --fails----------> PADDING is the trigger (new code) --> fix seed_poll/chunker --> P7 test
```

## Time-box

P1, P2b and P2c first (one host session plus one short device session). If none names the fault, the record stands at
**"device verified to 2 blocks and to block-source definitions"**, and the next work is the clock and the
compiler-removal decision — neither depends on this bug, and both lower the toll for every later result.
