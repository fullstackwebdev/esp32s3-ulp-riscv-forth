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
