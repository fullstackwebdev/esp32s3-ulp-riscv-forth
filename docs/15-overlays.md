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
