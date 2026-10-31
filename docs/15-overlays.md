# 15 — Overlays: what the friend's plan got right, and what the code says

Written on the `overlay-manager` branch. The discussion that prompted this was written **without access to the
source**, so every claim below is checked against the tree. Status: the overlay manager is implemented,
device-verified, and **not merged** — it costs 361 B of app space (below), which is a product decision, not a
bug.

## What he got right from a memory map alone

| Claim | Verdict |
|---|---|
| `V_HERE` at offset 4, `V_LATEST` at offset 8 | **Exactly right.** `enum { V_STATE=0, V_HERE=4, V_LATEST=8, PAD=12, DICT=44 }` |
| "Headers grow down and code grows up, so restoring two pointers undoes everything an overlay defined" | **Right**, and it is the whole trick. Rewinding `V_HERE` and `V_LATEST` to the sealed pair removes an overlay completely — no per-word undo, no compaction. |
| "`SEAL`/`OVL` is about 40 B of dictionary, including two 9 B variables" | **Close**: 69 B of code + 27 B of headers for 9 words = 96 B of dictionary. |
| "One window, one block" | **Right**: `BLKSZ` 128, one buffer at `BLKADR = MEMSZ - BLKSZ`. |
| "A collision with a resident word would silently shadow it" | **Right, and it is the unreportable failure** on this machine: `find()` returns the first hash match walking from `V_LATEST` upward, so an overlay word shadows a resident one for as long as the overlay is loaded. |
| "Stop tasks before `OVL`" | **Right.** Two task slots, each with its own `IP`; a task mid-flight inside overlay code resumes into rewound memory. There is no guard (a task-status primitive would cost ~15 B); the rule is documented instead. |

## What was already solved in this design (his point 1 is moot)

He worried that "the mailbox lives in `.bss`, outside `mem[]`, so Forth can't address it" and proposed moving it
into the sys-var area to avoid a new primitive. In this tree **both halves are already true of the design**:

- the window is *inside* `mem[]` (`BLKADR`), so `C@`/`C!`/`@`/`!` reach block data directly — the Forth layer
  never spells the buffer address as a literal (`tests/blocks.fs` gets it from `BLOCK` itself);
- the mailbox handshake is already a primitive (`BLKXFER`), and `BLOCK`/`UPDATE`/`SAVE` are C primitives
  (`-DBLKPRIM`), so no Forth-side doorbell code exists.

## What he assumed that did not exist: `LOAD`

He wrote "since `BLOCK`, `LOAD` and `SAVE` exist". `BLOCK` and `SAVE` did; **`LOAD` did not**, and neither did
`EVALUATE` or `MARKER`. That is the one real gap, and it is small only because of a happy accident in the
engine: `interpret()` is a **standalone function** that parses tokens out of `tib[ti..tl]` — the REPL is just
"fill `tib`, then call `interpret()`". So `LOAD` is a copy of the block into `tib` plus one call. This branch
adds it as a primitive (`p_load`, `-DOVL_LOAD`).

## His rule 4, answered: this `LOAD` copies, it does not point at the window

He asked whether `LOAD` reads the window directly or copies into `tib`, because a compile-time `BLOCK` inside an
overlay overwrites its own source mid-compile. **This one copies**, which mostly removes the hazard:

- `tib` is a fixed array, not a pointer into the window, so there is nothing to redirect anyway;
- an overlay whose text calls `BLOCK` re-fetches the window, but the chunk being compiled is already in `tib`.
  Only the **unread tail** of the same block can be lost — and only for blocks longer than one chunk.

The chunking is forced by a real constraint he could not have known: **the chip's `TIBSZ` is 96 while a block is
128 B**, so a block *never* fits one pass. The first version of `p_load` was a single bounded copy that would have
silently dropped the last 32 bytes of every block — source that compiles in the bake and vanishes on the chip. It
now chunks, cutting each chunk back to the last space so no token is split.

## What it costs on this machine (measured)

| | main | `overlay-manager` |
|---|---|---|
| dictionary | 86 words | 95 words (`VH VL bh bl ovlrun SEAL OVL GO` + `LOAD`) |
| `.text` | 4 592 | 4 824 (+232) |
| image code area | 366 | 444 |
| headers | 258 | 285 |
| `MEMSZ` | 2 296 | 2 040 |
| **free app space** | **1 544** | **1 183** |

The pool is the binding constraint: `LOAD`'s text puts the image 255 B over, and `mem[]` *is* the image, so
`MEMSZ` must drop 1:1. `flash_safe` refused the oversized image (exit 1) at 2 296 and at 2 062 (the twin was 11 B
optimistic, as usual); 2 040 fits with 25 B of pool spare.

**So the capability is bought with the very space it makes optional.** What it changes is the *shape* of the
limit: without overlays a program is at most 1 544 B, ever. With them each phase gets ~1 183 B *and can be
discarded*, so a 3 000 B program becomes possible in phases — bounded by block storage, not by `mem[]`.

## Two findings this branch paid for

1. **`SEAL` and `OVL` write to different kinds of address.** `HERE`/`LATEST` are *getters* (they push the value
   of the sys-var). `SEAL` must store into its own cells (`HERE bh !`), while `OVL` must store *into the
   sys-vars* (`bh @ VH !`, where `VH` is the sys-var's address). Writing `HERE VH !` in `SEAL` is a no-op that
   leaves `bh` at 0, so the next `OVL` rewinds the dictionary to address 0 and every word becomes unfindable.
   Measured as `0:?` on the first overlay line.
2. **Changing `MEMSZ` moves `BLKADR`, and the main core caches the window offset.** An ULP-only flash from 2 040
   to 2 050 (BLKADR 1 912 → 1 922) made `SAVE` still succeed while every `LOAD` read was **nacked**
   (`MSG_ERR_UNNAMED`, printed as `?`). Reflashing at 2 040 restored block I/O with no other change. Anyone
   moving `MEMSZ` on this system must reflash the main core too, or block reads will fail with an unnamed status.

## Device evidence (MEMSZ 2 040, pool 7 831/7 856)

```
0 BLOCK CONSTANT W          -> 1912 (the window, from the engine)
: B ...   B                -> blank the block
<12 pokes> UPDATE SAVE .   -> 0 (BK_OK)
: RES 7 . ;   SEAL
0 OVL                      -> ok
HI                         -> 42      (a word that exists only while block 0 is loaded)
' HI ovlrun !   GO         -> 42      (hook call: EXECUTE through a resident cell)
2 OVL                      -> rewinds; block 2 is empty
HERE bh @ = .              -> -1      (both pointers exactly the sealed values)
LATEST bl @ = .            -> -1
RES                        -> 7       (sealed word survives the overlay's removal)
2 3 + .                    -> 5       (REPL intact)
LATEST HERE - .            -> 1114    (1 183 sealed, less the 69 B of test words)
```

Host side: `tests/overlay.fs` runs the same protocol against the fake block server and passes
(`004242-1-1-17HI?`), gated on the `blocks`/`overlay` binaries that carry `-DP33_BLOCK -DOVL_LOAD`.

## If this is ever merged

- `LOAD` needs a *second* consumer decision: it is one primitive and one baked file (`src/p39b_overlay.fs`), and
  it is `-DOVL_LOAD`-gated so every older variant still compiles to its own bytes.
- The 361 B is recoverable if the overlay words move into the *bake* only as source in a block rather than baked
  into `mem[]` — an overlay can load the manager itself (`block 1` = `SEAL`/`OVL`/`GO`), which would remove 96 B
  of dictionary and keep the boot image lean. Not measured yet; noted as the obvious next step.

---

## Probe results for the five verification tests (branch state)

### 1. Block store size — ANSWERED, and it invalidated the premise

`main/repl_main.c` had `#define BLK_N 8`, i.e. **8 blocks = 1 024 B of source**, about 600-800 B of compiled
code — *less than the 1 183 B of resident app space*. Overlays could not have raised the program ceiling at
all. Measured on the board before the change: blocks 0..7 answered, 8..10 nacked. Raised to `BLK_N 128`
(16 KB of host RAM; the ULP's RAM is the scarce side). Re-measured on the chip after reflashing both cores:
blocks 0..127 answer and 128 answers `ERR_RANGE -5`.

Two fixes came out of it:
- the range nack was `mb[2] = 2`, and `blk_xfer` decodes a nack as `(i32)(0u - st)`, so "no such block"
  arrived in Forth as `ERR_BUSY`. It now sends 5 (`BK_RANGE`), and `blk_errmsg` learned to name `BK_RANGE`
  (it had been falling back to `ERR_UNNAMED -5`).
- the CRC nack had the mirror-image bug: `0xFFFFFFFC` decodes as **+4**, not −4; it now sends 4.

### 2. A real multi-phase program larger than the resident image — NOT ATTEMPTED

It is possible now that the store is 128 blocks, but nothing was written. The claim "overlays raise the
ceiling" remains **unverified at scale**, exactly as stated above.

### 3. Reload loop for leaks — PASSES ON THE HOST

`tests/overlay.fs` runs 20 × (load block 0, load empty block 2) = 40 overlay loads, then asserts both pointers
are back to the sealed values. Host: passes. Device: **not verified** (blocked by item 5).

### 4. Name-collision check — IMPLEMENTED, PASSES ON THE HOST

`V_SEAL` (sys-var 12, costs 4 B of app space: `PAD` 12→16, `DICT` 44→48) is published by `SEAL`;
`mkentry` refuses any definition whose 12-bit hash matches a resident header. `tests/overlay_collide.fs`
proves the refusal **and the aftermath** (`ERR_DICT`, then `RES` still prints 7, both pointers unmoved).
That test needed a host-only `-k` ("keep loading after an error") in `load()`, because the error is the
assertion and the point is what survives it; `-k` is under `#ifndef IMAGE`, so the chip pays nothing.

Two dead ends paid for here:
- the check first lived in a helper called from `mkhdr_pad` that recomputed `hash_pad(PAD)`; at that point PAD
  no longer held the name, so `hs` was the hash of an empty name (1285 = LOAD's hash) and **every** definition
  after `SEAL` was refused.
- `mkhdr_pad` wrote its 2-byte code field and advanced `V_HERE` **before** the check, so a refused definition
  still moved `HERE`; it now calls `mkentry` first and writes only on success.
Estimated false-positive rate is real, not theoretical: ~2.3 % per definition (98 resident words in a
4 096-value band), so names do get refused and renaming is the fix.

### 5. `PHASE` (call-site transparency) — PASSES ON THE HOST, BROKEN ON THE CHIP

`PHASE ( blk -- )` remembers the loaded block in a cell and skips the reload; host transcript shows `0 PHASE`
then `HI` → 42 and `XT1 XT2 =` → -1 (same word, no second definition).

**On the chip it fails.** `0 PHASE` returns an ambiguous `?`, and one block request that times out leaves
`blk_out` set, so every later request answers `ERR_BUSY` until reset — one lost request poisons the session.
What has been isolated on hardware:
- `0 LOAD` of a block containing **only execution** (`42 .`) works and prints 42;
- `0 LOAD` of a block containing a **definition** (`: HI 42 . ;`) fails with `?`, both with and without a
  seal, so it is not the collision check;
- no resident name hashes to `HI`'s 982 (checked over all 98), so it is not a seal refusal;
- `' LOAD` resolves to 3952 (tagged id 71) and `' PHASE`/`' SEAL`/`' OVL` resolve to real xrs, so the
  dictionary and the dispatch are present.
So: definitions issued from inside `p_load`'s nested `interpret()` fail on the chip while the same text typed
at the prompt compiles. That is a regression introduced by this session's engine changes (seal check,
`PAD`/`DICT` shift, or the `mkhdr_pad` reordering) and it is **not understood yet** — do not merge this branch
until it is. The next probe: log the token `word()` returns and `PAD`'s length from inside `p_load` on the
host build with `MEMSZ`/dictionary shaped like the chip's (baked image), since the host currently passes only
because it compiles the prelude from source.

---

## The chip-only failure: the C stack, measured (hypothesis confirmed structurally)

The friend's guess — stack, not logic — turned out to fit the memory map exactly:

- `build/esp-idf/main/ulp_main/ulp_main.ld`: `PROVIDE ( ulp___stack_top = 0x50001ff0 )`. The stack grows **down
  from the top of RTC RAM**, i.e. straight into `.bss` — where `blk_out`, `tib`, `srv` and `mailbox` live. So an
  overflow corrupts engine state instead of faulting, which is why the symptom is an ambiguous `?` and a
  `blk_out` that stays latched.
- Reserve = 0x1ff0 (8176) − pool (7849) ≈ **327 B**.
- `-fstack-usage` on the real ULP compile (frames, not code size):

| function | frame |
|---|---|
| `vm_enter` | **80 B** (the 2 270 B is code; the frame is small — but it is re-entered) |
| `interpret` | 48 B |
| `mkhdr`, `word`, `blk_xfer`, `cw` | 32 B each |
| `hash_pad`, `find`, `err`, `errf_msg` | 16 B each |

Chain sums:
- prompt path `main 32 → interpret 48 → vm_enter 80 → mkentry → hash_pad 16` ≈ **208 B** — fits.
- `LOAD` path `main 32 → interpret 48 → vm_enter 80 → p_load → interpret 48 → vm_enter 80 → mkhdr 32 → hash_pad 16`
  ≈ **336 B** — exceeds 327 B. Execution-only text (`42 .`) never re-enters `vm_enter`, which is exactly why
  `0 LOAD` of `42 .` works on the chip and `: HI 42 . ;` does not.

### What the cheap fix costs, measured

Making `interpret`'s per-iteration locals `static` (safe: none is live across a re-entrant call) takes 16 B out
of the chain (48 → 32) and adds **43 B of `.text`** — i.e. it would buy 16 B of stack with 43 B of app space.
Rejected and reverted; recorded here so nobody repeats it.

### The two fixes worth doing, both decisions rather than cleanups

1. **Remove the nesting instead of shrinking it.** `LOAD` should hand the block to the OUTER interpreter
   (a pending-block sys-var consumed by `interpret`'s loop) rather than calling `interpret` recursively. That
   removes an entire `interpret 48 + vm_enter 80` from the chain (−128 B) at the cost of a sys-var and ~30-40 B
   of text, and it changes `LOAD` to deferred semantics (the block runs when the current line's tokens are
   exhausted), which must be documented loudly.
2. **Buy stack with `MEMSZ`.** The stack is the gap above `.bss`, so `MEMSZ −64` gives +64 B of stack at 64 B of
   app space. At the current `MEMSZ` 1968 / 1052 B free, that is a 6 % app-space cost for ~20 % more headroom.

### `blk_out` latching

Deliberate (`a request nobody answered is still out there`), and **recoverable without a reset** —
`0 2 BLKXFER` sends `BLK_ABORT`, which clears it. That escape hatch is not discoverable from the `ERR_BUSY` the
operator sees, so every later request looks like a dead server. Either name the recovery in the message or
clear the latch when the status has been observed as stale; that is a design call, not a bug I should silently
"fix" by dropping the latch.

### `LOAD` also ends the line, and the same fix cures both

While testing the ti/tl question: `0 LOAD 99 .` prints only what the block prints; the `99 .` after it never
runs. Saving and restoring `ti`/`tl` in `p_load` was tried and **is provably not the cause** — instrumented, the
save reads `ti=6 tl=11` and the restore writes `ti=6 tl=11`, and the tail still does not execute, with no error
reported. So the nested `interpret()` leaves interpreter state such that the OUTER loop does not resume (the
`run()`/`vm_enter` line state, not the source cursor). Reverted; the patch bought nothing.

This converges with the stack finding: both problems are consequences of `LOAD` calling `interpret()`
recursively. **One fix addresses both.** `LOAD` should stash the block (a pending-block sys-var) and return,
and `interpret`'s loop should pull the next chunk when its own `tib` is exhausted. That:

- removes an `interpret 48 + vm_enter 80` frame from the deepest chain (−128 B against a ≈327 B reserve, which is
  the actual reason definitions fail on the chip);
- leaves the outer line state untouched, so a `LOAD` in mid-line behaves like any other word;
- costs a sys-var (4 B of app space) and roughly 30-40 B of `.text`, and changes `LOAD` to *deferred* semantics
  (the block runs after the current line's tokens), which has to be documented loudly rather than discovered.

### Alignment: ruled out

The new seal check (`mkentry`) touches headers with **byte** reads only (`mem[s+2]`, `mem[s+1]`), exactly like
`find()`, never a `*(u32 *)` or `rd16` on a header/PAD address. And an unaligned halfword on this target does
not corrupt silently: `rd16` calls `pl_halt(0x50)` on an odd address. So the x86-vs-chip asymmetry that the
alignment theory needs has no mechanism here.

### Baked image vs engine constants

Checked on the chip after the `PAD 12→16` / `DICT 44→48` move: `4 @` = 554 (V_HERE), `8 @` = 1537 (V_LATEST),
`12 @` = 1537 (V_SEAL, equal to V_LATEST right after `SEAL`, as it must be), `0 BLOCK .` = 1840 = `MEMSZ 1968 −
BLKSZ 128`. The bake, the engine and the chip agree, so the constants are not the failure.

---

## FIXED: the source switch (the friend's design) — device-verified

`LOAD` no longer calls `interpret()`. `p_load` fetches the block once and arms `V_LOADB` (0 = none, else
`(block+1) | (offset << 8)`); `word()` — the only reader of `tib`, confirmed by grep: no `parse`, `[CHAR]` or
`[']` variant exists in this engine — refills `tib` from the block when the current source is dry, and when the
block is exhausted the saved line resumes exactly where it was.

That single change fixed both outstanding bugs:

- **stack**: the deepest chain lost the extra `interpret + vm_enter`. `-fstack-usage` now gives
  `main 96 → vm_enter 64 → mkentry → hash_pad 16` ≈ **200 B** against a **339 B** reserve: ~139 B of margin,
  where the old chain was ~336 B and over.
- **lost tail**: `0 LOAD 99 .` now prints the block's output *and* `99`, in that order.
- **definitions from a block**: `0 PHASE` → `HI` → **42** on the chip, which never worked before.

Two guards make the deferred semantics loud rather than silent:

1. `PHASE` clears the hook cell, so `PHASE GO` on one line executes token 0 — and `EXECUTE` of token 0 is now a
   **named error**; it used to dispatch into `mem[0..1]` (`V_STATE = 0` → DOCOL) and run garbage from address 2.
   A phase block must set the hook in its own text.
2. An error disarms `V_LOADB`, so the remains of a half-loaded block cannot be fed to the next line.

Device run, all 30 checks green (`MEMSZ` 1936, pool 7 853/7 856, 98 words, 1 008 B free):
blocks 0..127 answer and 128 → `ERR_RANGE`; `0 PHASE` → `HI` → 42; `0 OVL` → `HI` → 42; 40 overlay loads leave
`HERE`/`LATEST` exactly at the sealed values; `1 OVL` of a block redefining `RES` → `ERR_DICT` and `RES` still
prints 7.

### Still open (named, not hidden)

- **Test 2** — a real multi-phase program bigger than one image (Tiny BASIC) — is now *possible* (128-block
  store, working definitions) and still **not written**. It is the test that decides whether overlays are worth
  their 536 B of resident cost.
- `ERR_BUSY` still does not print its own escape hatch (`0 2 BLKXFER` sends `BLK_ABORT` and clears the latch);
  naming it costs `.rodata` bytes, so it is a deliberate pending trade.
- The real host's **checksum-mismatch nack** is not covered by any test: the engine's fake server takes a
  different path, so the magnitude-of-the-negative-status fix is correct by rule, not by evidence.
- A **stack canary** painted from the main core (which can write RTC RAM) would turn the arithmetic into a
  measurement; the arithmetic plus a working chip says it is no longer urgent, but it belongs in the probe rules.

---

## Step 0 done: collision coverage, naming, and a seeder (the run-up to test 2)

- **The scan now starts at `V_LATEST`, not `V_SEAL`.** `V_SEAL` remains only the on/off gate, so the check
  compares a new name against the overlay's own entries *and* every resident one. It previously covered
  resident headers alone, which made two names colliding inside one phase invisible — and with p ≈ 2.4 % per
  name, a 40-name phase has a **62 %** chance of at least one collision, so an intra-overlay one would routinely
  hide among the loud ones. `tests/overlay_collide.fs` now proves the intra-overlay case (`DUPE` defined twice
  → second refused, first survives and prints 1).
- **The refusal names the offending token** (`RES?`) instead of printing `ERR_DICT`: `PAD` still holds the name
  when the check runs, so `err()` costs nothing where a new message would cost `.rodata`. The doc rule is now
  "a name followed by `?` during an overlay load = collision".
- **`tools/blkseed.py`** writes a source file into the store over the REPL (blank → pokes → `UPDATE` → `SAVE`,
  plus `--verify` to read every byte back). It refuses to build a line longer than 88 characters, because
  TIBSZ is 96 on the chip and an over-long line is dropped **after** being partly poked — that would seed a
  block with holes.

### The verdict arithmetic, and what a phase actually costs

Total with overlays = `R + N × (1008 − R)`, where `R` is the *resident program* part. Beating the 1 544 B
monolith therefore needs:

| phases | resident part R | per-phase room |
|---|---|---|
| 2 | < 472 B | > 536 B |
| 3 | < 740 B | > 268 B |

Measured density on this engine: **~142 B of compiled code per 6 lines of source (~24 B/line)**. So a ~700 B
phase is ~28 lines, and three of them plus a small resident core is ~85 lines → predicted total ≈ 2 100 B,
**+36 %** over the monolith. That is the number test 2 has to confirm or refute, and if it does not beat 1 544 B
the 536 B gets banked.

### Two facts test 2 depends on, recorded before it runs

- **The store is volatile.** `blkfile[BLK_N][BLK_SZ]` is host `.bss`: a paged program survives only within one
  power cycle unless the main core is taught to persist it (NVS or a flash partition). That is cheap in ULP
  bytes and not yet done; test 2 is scoped to a single power cycle deliberately.
- **Phase size is capped by the resident part**, not by free space: each phase gets `1008 − R` bytes. A BASIC
  whose resident state (token store, variables, helpers) is 600-900 B would leave phases of 100-400 B, i.e. too
  small for a tokenizer — which is why test 2 starts with a numeric program whose resident core is ~40 B and
  writes its data through the block window instead of a resident array.

---

## Test 2 (the capacity claim): scaffolded, HALF DONE — no verdict yet

This is the test that decides whether overlays are worth their 536 B, so its state is recorded precisely.

**Done and verified**
- The host fake server now serves 64 blocks (host `.bss` only, 0 B on the chip) instead of 4, keeping the two
  deliberate failures the other tests depend on by number: block 5 never answers (`blocks_noserver.fs`), block 7
  answers with a bad checksum (`blocks.fs`). Blocks 8-63 now answer, which is what makes multi-block phases
  possible in an automated test.
- `tools/blkseed.py` seeds any source file into the store over the REPL (blank → pokes → `UPDATE` → `SAVE`,
  `--verify` reads every byte back), refusing lines over 88 chars because TIBSZ is 96 on the chip.
- **Phase A is correct and measured**: `tests/capacity_a.fsx` fills the data window, then computes sum, sum of
  squares, XOR fold, min and max with one plain loop per statistic. On the host at the shipping `MEMSZ` it
  prints `8128 690880 0 0 127`, matching a Python re-derivation exactly, and compiles to **606 B**
  (`HERE` 506 → 1 112) with 7 headers.

**Not done**
- Phase B (`tests/capacity_b.fsx`) — independent recount, 16-bucket histogram, parity, threshold count and
  longest ascending run — is written but **fails at run time** and its numbers do not yet match the Python
  model. Expected numbers for the deterministic fill (`tab[i] = i`) are `8128`, sixteen `8`s, `64 64 64 127`.
- No generator, no wiring into `tests/run.sh`, no `.expected` transcript, and therefore **no measured total**.
  The claim "a paged program exceeds the 1 544 B single-image size" remains **unproven**.

**Arithmetic that the finished test must confirm**: total = 606 (phase A) + phase B, so phase B must compile to
**≥ 939 B** to clear 1 544 B, and must stay ≤ ~1 008 B (the sealed free space). That is a 939-1 008 B window:
achievable, but the finished test has to hit it rather than be assumed to.

### Two bugs this scaffolding already paid for

- `TAB` re-fetched the block on every access (`: TAB DATABLK BLOCK ;`), so every `C!` write was undone by the
  next read and the statistics ran on the store's old contents — measured as a sum of 1 171 for a window that
  should have held 0..127. A phase must cache the window address in its own cell and fetch once.
- Phase source lines must be **short**. On the chip `TIBSZ` is 96, so a 144-char definition is refused
  (`line too long`) — and worse, through the block path an over-long line would be dropped after being partly
  poked. Definitions are split across lines; `blkseed.py` refuses over-long lines for the same reason.

---

## Test 2, ASSERTED IN THE SUITE: three phases compile to 1 852 B (+19 % over the monolith)

Each phase was compiled at the shipping `MEMSZ` 1936 (sealed `HERE` 506) and its size read from the `HERE`
delta:

| phase | job | compiled | fits 1 008 B? |
|---|---|---|---|
| A | fill the data window, then sum / sumsq / xor / min / max | **606 B** | yes |
| B | scans 1-6: sum, zeros, >63, even, odd, sumsq | **538 B** | yes |
| C | scans 7-12: /3, /5, ==127, <64, even-index sum, max | **568 B** | yes |
| | **total** | **1 712 B** | **+11 % over the 1 544 B monolith** |

Phase A's and B/C's numbers are each checked against an independent Python derivation over the deterministic
fill `tab[i] = i` (A: `8128 690880 0 0 127`; B: `8128 1 64 64 64 690880`; C: `43 26 1 64 4032 127`) — all three
match exactly, so the sizes above are sizes of *correct* code, not of code that merely compiles.

So the claim "a paged program exceeds the single-image size" now holds **by measurement of the phases
themselves** at the shipping memory size: 1 712 B > 1 544 B, with each phase individually under the 1 008 B
window. What is *not* yet demonstrated end-to-end is the same program travelling through the block store.

### Why the end-to-end test is not landed yet (one bug, named)

`tests/overlay_capacity.fs` is generated by `tools/mkcapacity.py` (26 phase blocks, comments stripped, chunks cut
at spaces, 6 pokes per line) and it loads phase A from blocks 8.. under the deferred source switch — but the load
still fails with a **token arriving in two halves** (`SS?`, from `DOSS`). Each phase file loads correctly on its
own, so the fault is in the block transport/splice, not in the phases or the engine. The generator has already
fixed three such faults the same way:

- `\` comments must be stripped before seeding: a block has no line structure, so a comment swallows the rest of
  the chunk (measured: `TEXT?`).
- chunks must be cut at **spaces**: fixed 128-byte cuts splice a token across two blocks (`ETER?` from
  `LITERAL`).
- 6 pokes per line, not 7-8: three-digit codes push `NNN W KK + C!` past the chip's `TIBSZ` 96, and a dropped
  poke line leaves a hole (`SS?` was first seen this way).

Verdict so far, honestly stated: **the capacity claim is measured and positive (+11 %, 1 712 B)**, and it is
11 %, not the +36 % the earlier density estimate predicted, because three phases of ~600 B is what the authoring
actually produced. A larger margin needs more scans per phase (each phase can hold up to 1 008 B, so ~50 % more
again is available), which is authoring, not engineering.


---

## Test 2 is now a suite test that can fail (`tests/capacity.sh`)

Run every build by `tests/run.sh`, it measures each phase's compiled size at the shipping `MEMSZ` 1936 from the
`HERE` delta and asserts three things:

| | measured | assertion |
|---|---|---|
| phase A — fill, then sum / sumsq / xor / min / max | **606 B** ≤ 1 008 | fits the sealed window |
| phase B — scans 1-6 | **608 B** ≤ 1 008 | fits |
| phase C — scans 7-12 | **638 B** ≤ 1 008 | fits |
| **total** | **1 852 B** > 1 544 | **paged program beats the largest single image, +19 %** |

It also asserts the *numbers* each phase prints, as concatenated digits derived independently in Python
(`812869088000127`, `81281646464690880`, `43261644032127`), so a phase that still compiles but computes wrongly
fails the test.

Verified that it can fail: with `LIMIT` raised to 2 000 the test prints `FAIL (does not exceed the monolith)` and
exits 1. A test that cannot fail would not be evidence.

Scope, stated plainly: this measures **capacity** — three phases, each rewound before the next, driven from
files. The **block transport** is asserted separately by `tests/overlay.fs` and `tests/overlay_collide.fs` (a
block-defined word loads, runs through a hook, is refused on a resident collision, and 40 load/drop cycles leave
both pointers sealed). What is still *not* covered is a multi-block phase travelling through the store:
`tools/mkcapacity.py` generates that test and it fails on a chunk boundary that still crosses a block wrongly;
the generated attempt is shelved in `tests/fixtures/overlay_capacity_wip.fs` rather than deleted, and the three
generator faults found on the way are recorded in its GUARDRAILs (backslash comments swallow a chunk, fixed
128-byte cuts splice tokens, and a cut between definitions is the only safe boundary).

---

## The A/B, row by row (state of the evidence)

Control = the same program as ONE image in an engine built **without** overlays (`artifacts/host_ctl`,
its own best MEMSZ 2296). After = three phases rewound between loads, plus the resident event loop.
Every number below is read from a run in this tree; nothing is estimated.

| # | metric | control | after | verdict |
|---|---|---|---|---|
| 1 | free space at the prompt | **1 536 B** (measured on this engine, not the historical 1 544) | **690 B** (chip and host agree) | **FAIL**: the loop costs 318 B, not the ≤150 B budget. Recorded, not hidden. |
| 2 | largest program that loads | stops with **ERR_DICT** inside phase C | **1 692 B** across three phases (A 606, B 608, C 478) | **PASS**: +10 % over the control, every phase ≤ 690 B |
| 3 | capability | phase C's statistics never print | phase C's statistics print (`43264032127`) | **PASS**, asserted as a diff in `tests/abtest.sh` |
| 5 | block round trips per event | n/a | 2 same-phase events → `brt` = **1** | **PASS** (`tests/loop.fs`) |
| 6 | event latency | n/a | **not measurable**: `MS` is a *delay*, not a clock | blocked on instrumentation |
| 7 | phase switch cost | n/a | **not measurable** for the same reason | blocked on instrumentation |
| 8 | queue overflow | n/a | 5th event into a 4-slot ring → `qovf` = 1, event rejected | **PASS** (rejected and counted; this engine has no Forth-level message primitive, so it is countable rather than named) |
| 9 | 50-cycle rotation | n/a | `HERE` and `LATEST` equal the sealed values; host and chip | **PASS** |
| 10 | stack high-water | — | canary **paints** the 320 B above the pool from the main core at 0 ULP bytes, but the report cannot be read: the main console is not the ULP's port | **blocked on readout plumbing** |
| 11 | stale hook | — | `PHASE GO` on one line → named error (EXECUTE of token 0) | **PASS** |
| 12 | name collision, resident **and** intra-phase | — | both refused, `HERE`/`LATEST` unmoved, offender named | **PASS** |
| 13 | failed load then RESET | — | `99 OVL` → `ERR_NO_BLKSERVER`-class failure by name; after `BLKXFER` abort + `RESET`, `curblk` = -1 and the next load works | **PASS** |
| 14 | handler that calls PHASE/PUMP | — | structurally impossible: PUMP arms the switch and `EXIT`s, so no handler runs while its own code is being erased | **PASS by construction** (documented rule, not a check) |
| 15 | arming a load from inside a loaded block | — | chip transcript: `42` (tail runs), `V_LOADB`=10, then `222` (armed block runs) | **PASS** |
| 4 | data capacity 4 KB / 16 KB | 128 B window | not run: the host fake serves 64 blocks and the chip sweep needs ~5 min of device time | **not done** |

### What this means

The capacity claim is real and measured with a control: **1 692 B paged vs 1 536 B control (+10 %)**, and the
capability difference is a transcript rather than a claim. The price is also real and worse than predicted: the
event loop costs **318 B**, so the prompt has 690 B instead of 1 008 B and each phase's window shrinks with it —
which is why phase C had to be trimmed from six scans to four. Rows 6, 7, 10 and 4 are instrumentation gaps, not
results, and are listed as such. On the evidence so far the A/B is **positive but thin**: +10 % capacity for a
318 B regression and a rules-based programming model (handlers run to completion, phases are swapped by a
resident loop, cross-phase work is an event).

---

## Unlocking the "positive but thin" verdict: the questions, and what is measured

The verdict is positive but thin (+10 % capacity, 318 B of loop). The friend's correction is right: the cost is
FIXED and the benefit scales with phase count, so the deciding number is not 3 phases but N. These are the
questions that unlock it, with what the tree can answer today.

**Answered by measurement**

- *Where did the 318 B go?* Attributing it word by word (`PUMP` 156 B, `RESET` 49 B, the rest in cells, `POST`,
  `EV?`, `EV@` and `PHASE`'s round-trip counter). `RESET` was six stores for four that matter; trimming it and
  making an event *be* a block number (dropping the `8 +` map) recovered 14 B → **704 B free**.
- *What is the cost per additional phase?* Zero resident bytes: a phase is code that lives in the overlay area
  and is discarded. The fixed toll is the manager + loop; the scaling part is each phase's own size.
- *What limits a phase?* `LATEST HERE -` at the prompt: 704 B now. Phase A is 606 B, so there is room for one
  phase of that size, not two.
- *Does the store hold what a 6-phase program needs?* 128 blocks × 128 B = 16 KB of source; at the measured
  density (~24 B of source per B of compiled code) that is ~4-5 KB of code — enough for ~6 phases.
- *What breaks when a phase touches paged data?* **The window holds ONE block.** Fetching the data block and the
  destination block and keeping both addresses silently reads the wrong bytes (measured: histogram buckets
  summing to 44 instead of 128). The legal pattern is read → compute in phase-local cells → fetch the
  destination → write → `SAVE`. `UPDATE` alone leaves the store's old bytes (measured: all zeros).

**Still open**

- *What is the marginal cost of the 4th, 5th, 6th phase?* Needs a program of that many phases. The flagship is
  started but shelved: `tests/fixtures/flagship_wip/` holds phase A (works, 606 B) and the histogram phase being
  rewritten to the one-window pattern, plus the note that D/E/F are unwritten.
- *Where is the stack high-water mark?* The canary paints and its channel exists (`/dev/ttyACM0` is present
  alongside the ULP's `/dev/ttyACM1`); the readout is a routing change, not ULP bytes.
- *What does a switch cost in time?* `MS` is a delay, not a clock, so this needs either a dispatcher counter
  (~8 B of `.text`) or a GPIO toggle plus a logic analyser. Not faked with host wall-clock.
- *Do overlays pay above ~1.5× the control?* Unanswered until a 6-phase program runs. Decision rule stands: under
  1.5× bank the bytes, above 2× the machinery has earned its place.
