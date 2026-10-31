# 20 — Strategy

> This strategy turns a measured **504 %** device capability into a usable, persistent one, and **each step has a number
> that can stop it.**

Written for branch `overlay-manager-enhancement`, after the overlay work landed on `main`. Every figure below is
measured in this tree unless it is explicitly labelled a prediction.

---

## 1. What we are optimising, in order (they conflict, so the order matters)

1. **Capability per phase × number of phases.** Store-bound, not RAM-bound: **15 phases × 516 B = 7 740 B = 504 %** of
   the 1 536 B control on the device; 604 % on the host.
2. **Velocity** — how fast a change can be learned from. Host suite 5.8 s; a device command is 20 ms (was 370 ms).
3. **Hard constraint: the REPL stays.** Interactive on-device development is the product. Removing the compiler would be
   a *different* product (deploy-only) and is out of scope for this branch.

## 2. Where we stand (measured)

| | |
|---|---|
| phase switch, source | **970.7 ms** median for 8 blocks (121 ms/block) |
| of that, UART round trip | **~50 ms/block** — the wire, not the machine |
| of that, parse + compile | **~70 ms/block** ≈ 0.55 ms per source char |
| store in use at the ceiling | **120 of 128 blocks** |
| store persistence | **none** — host `.bss`, a reset loses the program |
| resident toll | **846 B** (manager 528 + loop 318) |
| images | **absolute-addressed** (`cw()` writes tokens verbatim; `find()` walks headers by fixed stride) ⇒ valid only against the exact sealed `HERE`/`LATEST` |

## 3. The plan — each step has a gate that can stop it

| # | Step | Gate (a number that stops it) |
|---|---|---|
| **0** | **Assert phases 1, 8 and 15 *execute*** (same outputs as the host), not merely compile | Any phase runs wrong ⇒ stop; that is an engine bug and everything downstream is void |
| **1** | **Build-on-chip dump word** (~40 B of Forth): save `sealed HERE→HERE` (code) and `LATEST→sealed LATEST` (headers) into blocks | **Proceed to binary only if an image needs ≤ 65 % of the source blocks.** 8 → 5 blocks is 63 %: it passes, but only just, so measure it rather than assume |
| **2** | **A light real program**: a menu shell plus **one** tool, one phase each | If the tool needs state it cannot reach (resident or store) ⇒ the resident set is wrong; fix it *before* the binary loader hardens what must stay resident |
| **3** | **Binary overlays** (source stays the master copy; the REPL and compiler stay resident) | Loader must refuse loudly, each refusal shown failing first: resident-checksum mismatch, corrupt image byte, header collision |
| **4** | **Timing, before and after**, with the prediction already written (below) | **Prediction: ~5 blocks × ~50 ms ≈ 250 ms per switch, versus 970 ms now (≈4×).** A measurement near 970 ms means the loader is wrong, not that binary was a bad idea |
| **5** | **Flash-backed store** (raw `esp_partition`, dirty blocks cached, sector-aligned batched write-back) | Wake cost decides the always-on story: light-sleep wake per miss is fine; a deep-sleep reboot changes the programming model and must be said plainly |
| **6** | **Full real suite** (menu + line editor + calculator), one tool per phase | If two phases must call each other ⇒ this is a menu model, not one interwoven program; state it and stop pretending otherwise |
| **7** | **"Unbounded"** | Only after step 5 — size **and** persistence. Permitted sentence: *bounded by flash, not by the ULP's 8 KB of RAM, and the program survives reset* |

### Why binary overlays before flash

The store is the binding resource (120/128 blocks used). Binary overlays attack that directly and **remove a bug class**
— no parsing means no lost tail, no comment straddling, no stale-tail seeding, no 90-byte definition rule — and they
make `n PHASE GO` legal on one line because a binary load is a synchronous copy. Flash gives persistence and a bigger
bound, but it cannot be *sized* until step 1 says how many blocks an image needs. Doing flash first would build a bigger
warehouse for an unknown inventory.

---

## 4. Binary overlays: the constraints that decide success

**What the checksum must cover — pointers alone are not enough.** If a resident word's *body* is edited without
changing its length, `HERE` and `LATEST` are unchanged and every image silently points at changed code. The descriptor
must carry a checksum over:

- the **resident code area** (`DICT → sealed HERE`, ~500 B), and
- the **resident headers** (`sealed LATEST → HDRTOP`, ~300 B),

recomputed at load and compared. Summing ~800 B in Forth is slow, but it runs **once per phase switch**, which at
~800 bytes is far cheaper than the ~970 ms a source switch costs today.

**Loader negative tests** (each must be shown failing once before its guard exists):

| test | passes if |
|---|---|
| build an image, drop it, load it | `HERE`, `LATEST` and every scan output match the source-loaded phase |
| block count | binary blocks per phase **< ** source blocks, and the number is recorded |
| 50 load/drop cycles | pointers return to the sealed values every time |
| change one resident definition, load an old image | named refusal, nothing executes |
| corrupt one image byte | checksum failure by name |
| rename a word to collide with a resident one | refused by name |

**The dump word** must be written with `BEGIN … WHILE … REPEAT` — this machine has **no `DO`/`LOOP` and no `CMOVE`**.
Test the copy loop on a block whose contents are known *before* trusting it (the checksum-instrument lesson: two
"working" instruments printed the loop counter). Keep every typed line **under 63 bytes**, or seed the source into a
block and `N LOAD` it.

**Image build order is fixed**: reset → load resident set → `SEAL` → load the phase from source → dump. An image is
valid only against the exact resident set it was built on, so one script must do all five steps every time.

---

## 5. Velocity (T11, recorded in `docs/18-overlay-todos.md`)

Every coverage probe becomes a **verifier inside one entry point**, each stating its *correct* expectation, each
**shown able to fail**, in a **fast lane** (seconds) and a **complete lane** (tens of seconds), with wall times printed.
The acceleration levers are already measured: prompt-driven device IO **18.6×**, one-transcript batched seeding
**1.9×**, one reset per variant, parallel independent host checks.

---

## 6. Standing rules

1. **Claims carry a tier** — device / host / not measured. 604 % is host; 504 % is device.
2. **A check that has never failed is not evidence.** `--skip-block`, and `known_defects` expectations that state the
   *correct* behaviour.
3. **Never trade application space for a convenience without writing the trade down.** `.text`/`.rodata`/`.bss` and
   `MEMSZ` all come out of the same application-space budget, so "pay from `.text`" is not free money — it is a
   documented trade or it is a mistake.
4. **Fail loud at the source.** Every silent truncation found so far (block tail, 63-byte line, stale block tail) cost a
   debugging round; each is now a named refusal.
5. **Do not overfit the benchmark**: the control must keep failing `ERR_DICT`, and any checksum/DISP change is
   deliberate and documented in the same commit.

---

## 7. Accepted from review, and corrected by measurement

**Accepted:** the store is the binding resource · binary overlays are worth doing now · the REPL is untouched by them ·
a compiler-less runtime (option C) is a different product · fixed-base images need a checksum **and** loud refusal ·
block saving is ~40–50 % per phase, not 60 % · **the step-1 gate must be ≤ 65 %**, not "fewer than source" ·
the checksum must cover resident code *and* headers.

**Corrected by measurement:** a phase switch is **~1 s per 8-block phase → 121 ms/block**, not 0.5 s per block, and
**~50 ms of each block is the UART round trip** rather than compute.

---

## 8. Corrections the user guide needs

The guide is behind the branch. Fix these before it is published:

| guide says | actual |
|---|---|
| interactive line limit 127 bytes | **63 bytes** (`CMD_SIZE` 64); longer lines are **refused by name** — `line too long: N bytes, the ring holds 63 - NOT sent` |
| `DO … LOOP` available | **no `DO`/`LOOP`** on this machine (`DO?`); loops are `BEGIN … WHILE … REPEAT` |
| `DEPTH` available | **no `DEPTH`** (`DEPTH?`); stack depth needs a Forth-side counter |
| the program is stored persistently | the block store is **volatile** (host `.bss`) — a reset loses the program until step 5 |
| a definition must fit ~90 bytes | **retired**; a block may use the full 128 B. What still matters is that a definition must not straddle a **block** boundary in a driver-loaded phase, and `tools/fsplit.py` enforces it |
| collisions refused by name | still true, and the same message shape as "not found" (`NAME?`), so only `LATEST`/`HERE` deltas or a counter distinguish them |

---

## Step 1 result (measured on the device, three phase slots)

| | |
|---|---|
| phase source | 8 blocks, **811 B** of text |
| compiled | **code 516 B + headers 60 B** (20 definitions) = 576 B payload |
| block count | **packed 5 blocks (62 %)**, descriptor in its own block 6 (75 %) |
| gate (≤ 65 % of source blocks) | **PASS — by one block, exactly as the review predicted** |

Two consequences to carry into step 3:

- **The descriptor must share the block stream.** It is ~12 B against a 128 B block; giving it a block of its own costs
  the whole gate. This is also the difference between 62 % and 75 %, so the loader must pack the image at a block
  boundary rather than at whatever alignment `sealed HERE` happens to have.
- **The image writer cannot live in the overlay with the phase.** A Forth dumper compiles to ~370 B; the phase is 516 B;
  the window is ~690 B on the chip. Measured on the host as `ERR_DICT`. So the writer has to be **resident** (it costs
  application bytes — the trade must be written down and agreed before it lands) or live as a phase of its own, which
  removes it from the window at the moment it is needed to read that window.

Note also that the density gain here is **smaller than "no parsing" suggests**: the saving is text (811 B) versus code
plus headers (576 B) = 29 % in bytes, and block rounding turns that into 8 → 5. The remaining argument for binary is
therefore not density but **removing the parse bug class and the switch cost** — which step 4's prediction is about.

## Step 2 result: a menu phase and a tool phase, one block each (measured)

```
MENU  : MENU 7 6 BLOCK C! UPDATE SAVE DROP 77 EMIT ;     (writes the choice, prints 'M')
TOOL  : TOOL 6 BLOCK C@ 3 * 84 EMIT . ;                  (reads it back, prints 'T' and 21)
switch: 2 OVL  (drop the menu phase)  then  12 LOAD  (bring the tool in)
```

- **host:** `M` `T` `21` then the store reads `7` — the value crosses the phase switch **through the store**.
- **device:** `MENU-> M ok`, `TOOL-> T21 ok`, `store=7` — identical, so the handoff is real on the chip.
- **resident bytes added: 0.** The menu↔tool channel is a byte in a data block, exactly what the model claims.

### The finding the gate asked for

1. **A phase cannot name a block number it was not told.** `6` is hardcoded inside *both* phases here. In a real suite
   that constant has to be either resident (one 4-byte cell) or duplicated in every phase — and duplication is how the
   menu and the tool silently disagree after one edit. **Decision needed before the binary loader hardens it:** spend
   ~4 B of application space on shared block-number constants, or accept duplication. (Rule: no application bytes
   without agreement — this is the ask.)
2. **`2 OVL`/`LOAD` from the driver is the switch, and nothing else needs to be resident.** No handler calls another
   phase; the menu writes, returns, the driver swaps, the tool reads. The resident set does not grow with the number of
   tools.
3. **Block numbers are a shared namespace with reserved members.** Block 5 is the host test server's deliberately silent
   block and block 7 answers with a bad checksum; writing shared state to 5 measured `ERR_NO_SERVER` and then a latched
   `ERR_BUSY` that made every later block call fail. A real suite needs a reserved-range table, not conventions.

## Step 1 COMPLETE: the image is 5 packed blocks, verified byte-for-byte on the chip

Built by the **main core**, not by Forth. A Forth dumper cannot do it: given the same ~690 B window it needs ~370 B for
the copy loop plus the 516 B phase — measured as `ERR_DICT`, twice. The main core already reads the ULP's `mem[]`
(`ULP_RAM_BASE + ulp_repl_mem_addr`) and owns the block store, so `#d <blk> <code_start> <code_end> <hdr_start> <hdr_end>`
does the whole job at **zero ULP bytes**.

```
code [786,1302) = 516 B     headers [1421,1481) = 60 B
dump: code 516 + hdr 60 = 576 B, descriptor packed -> 5 blocks from block 40, sum 38914
offset   0: memory   2  image   2  MATCH
offset 127: memory  15  image  15  MATCH
offset 300: memory 208  image 208  MATCH
offset 500: memory 106  image 106  MATCH
```

| | |
|---|---|
| payload | 576 B (516 code + 60 headers, 20 definitions) |
| blocks | **5** with the descriptor packed into the first block's spare bytes = **62 % of 8 source blocks** |
| gate (≤ 65 %) | **PASS** |
| verification | 4 probes straddling block boundaries, all byte-exact |

### The `SB` trade, as decided

One resident base constant, `6 CONSTANT SB`. **Measured cost: 9 B** (3 B header + 2 B code field + 4 B cell), confirmed
both at the prompt and against the baked image. Phases now write `SB 1 +`, `SB 2 +` instead of repeating absolute block
numbers. `tests/sb_range_check.py` fails the suite if `SB` collides with the fixture blocks (5 silent, 7 bad checksum)
or with the 8‥127 phase range — `SB = 32` was rejected by exactly that check. The same check cross-checks
`tests/menu_tool.py`'s `DATA_BLK` against `SB`, so a menu and a tool cannot drift apart silently.

### Two defects found while building it

1. **`BLK_SZ` is not the transfer size.** `BLK_SZ` (256) is only the store array's row *width*; the transfer size is
   `blk_sz` (128), published by the ULP. Flushing on 256 packed two blocks into one row, so the ULP read the first 128
   bytes and everything after was invisible — image byte 0 matched while bytes 127, 300 and 500 did not.
2. **A silent block wedges the layer.** Writing shared state to fixture block 5 measured `ERR_NO_SERVER` followed by a
   **latched** `ERR_BUSY` on every later block call. `tools/devio.py` now sends `0 2 BLKXFER` (op 2 = BLK_ABORT) on any
   wedged reply, and exposes `abort_block()`.

### Scope note (the review's caveat, accepted)

This proves the image is **5 blocks and byte-exact**; it does not yet prove a loader can adopt it. Step 3 remains:
checksum over resident code + headers, the six refusal tests each shown failing first, and the switch-time comparison
against the ~250 ms prediction.

## Step 3 COMPLETE: the binary loader passes all six tests, and a switch is 26× faster

`#l <desc_blk>` adopts a packed image on the **main core** (zero ULP bytes): it validates, copies bytes into `mem[]`, and
sets `V_HERE`/`V_LATEST` — the same rewind the machine already trusts. The descriptor carries **two** sums, as the review
required: one over the image payload, one over the **resident dictionary** (`[52, code_start)` code plus
`[sealed LATEST, HDRTOP)` headers).

| test | result |
|---|---|
| T1 build → drop → adopt, then **execute** | **PASS** — cells `[6712, 353000, 0, 57, 128, 38]`, identical to the source-loaded phase |
| T2 block count | **PASS** — image 5 vs source 8 |
| T3 50 load/drop cycles | **PASS** — pointers return to the sealed values every time |
| T4 corrupt one image byte | **PASS** — `REFUSED image corrupt (sum 39169, descriptor 38914)` |
| T5 resident dictionary changed | **PASS** — `REFUSED resident dictionary changed (sum 31743, image built on 0)` |
| T6 image header shadowing a resident hash | **PASS** — `REFUSED name collision, image header hash 1338 shadows a resident word` |

**Switch time, measured (`2 OVL` + load, 10 samples, median):**

```
source switch:  991.7 ms      binary switch:  38.5 ms      -> 25.8x faster
prediction was ~250 ms; measured 38 ms (under prediction)
```

The prediction was deliberately pessimistic: it assumed ~50 ms per block of mailbox traffic. A `#l` is a **single**
command — five blocks are read by the main core with no per-block round trip at all — so the cost is one UART command
plus a 576-byte copy. That is why it lands at 38 ms rather than 250 ms.

### Three bugs found by the tests (each now a GUARDRAIL at the site)

1. **The loader folded the image into its own resident checksum.** The "resident" header range started at the *post-load*
   `LATEST` (the image's own base) instead of the **sealed** `LATEST`, so a clean image was refused for colliding with
   itself — and the refusal printed two byte-identical entries. Fixed by using `hs + hdr_len` (the sealed base).
2. **Forging a header byte trips the payload sum first**, so a naive collision test never reaches the collision check; the
   test now recomputes the sum, as a different builder would.
3. **Resident headers live in memory, not in a store block.** Reading `N BLOCK` (block 11 = phase source text) instead of
   `addr C@` meant the forgery copied source text and the loader correctly adopted it.

### Scope note

Six tests, all green, on the device. The loader is main-core code: **0 ULP bytes, 0 application bytes**. What is still
unproven is everything the strategy lists after this: flash-backed persistence, the light real suite beyond one menu +
one tool, and behaviour when the image was built against a *different* baked prelude (T5 proves the check fires when the
resident sum changes; it does not prove a rebuild-and-rebuild-every-image workflow).

## Review feedback that arrived one turn late: what still applies to what shipped

The design it proposes (loader on the main core) is what step 3 built. But three of its points are **live defects in
what shipped**, not history, and one of them invalidated a test I had already called green.

### 1. The console `#l` races the REPL — and that is exactly what the review forbade

`#l` writes `mem[]` from a console command while the ULP is running its REPL loop. It passes only because the ULP has
nothing to execute at that moment: no token is being fetched from the region being written. That is **passing by
timing**, which this project does not accept. The proposed fix is the right one: the ULP issues a "load image n"
request through the existing mailbox, blocks waiting for the status (it already spins inside `blk_xfer`), and the main
core writes `mem[]` while the ULP is provably quiescent. `#l` should then disappear or be refused.

**Cost answer (asked for before coding):** ops are plain mailbox words — `BLK_READ 0`, `BLK_WRITE 1`, `BLK_ABORT 2` —
and `BLKXFER` is `( n op -- status )`, so **a new op value costs 0 ULP bytes**; the ULP's existing path already carries
it and only skips the READ checksum. **But the host's `block_task` treats every op that is not READ as WRITE**
(`} else { /* WRITE */`), so an unknown op today nacks as `BK_CRC`/`+4` — a misleading name, in exactly the class the
engine's own GUARDRAILs complain about. Adding op 3 needs an explicit host branch *and* an explicit unknown-op refusal.

### 2. An image does not contain what a phase's *top-level text* did

Proven, not argued: after adopting the image, the six result cells already held
`[6712, 353000, 0, 57, 128, 38]` — because the dump was taken **after** the source phase ran, so those values were
baked into the captured bytes. My original T1 therefore proved only that the bytes came back. Clearing the cells and
calling the image's own entry word `RUNPH1` recomputed them, which *is* proof of execution — now folded into
`tests/loader_tests.py` (adopted / zeroed / after-RUNPH1 all printed).

So the review's gap is real:
- the descriptor needs an **entry xt**, returned by the load so the caller can `EXECUTE` it;
- a phase must **define things and nothing else** at top level — initial values belong in `CREATE … ,` data (captured
  in the image), not in `!` statements that a binary load skips;
- the dump must be taken **before the phase runs** (build order), so captured data holds initial values, not leftovers.

### 3. No explicit "wrong sealed pointers" refusal

`#l` copies to the destination recorded in the descriptor (`code_start`) rather than verifying it equals the machine's
**current** sealed `HERE`. Today a moved seal is caught only incidentally, by the resident checksum. The review asks for
a named status instead; that needs the current `bh`/`bl` in the request, which the mailbox flow provides for free.

### Capacity this implies (the review's arithmetic, checked against the measurement)

5 blocks per phase against a 128-block store ⇒ **about 25 phases**, roughly **12.9 KB** of code, ≈ 8× the 1 536 B
control, versus 15 phases for source phases. Packing image headers back to back approaches 28, leaving almost nothing
for data. **The code/data split must be decided before any capacity number is promised** — at 5 blocks/phase with, say,
16 blocks reserved for data, the honest figure is 22 phases (~11.3 KB).

### Housekeeping still open

- regression test for the `BLK_SZ` (256) vs `blk_sz` (128) defect: a known pattern **past offset 128**, so the bug
  cannot return silently;
- the user-guide corrections in §8 (63-byte line limit, no `DO/LOOP`, no `DEPTH`, volatile store, retired 90 B rule,
  collision refusal printing the same shape as not-found).

## Step 3b: the review's three items — two done, one blocked by the byte gate

### Done and on the device

**Entry xt in the descriptor (v2, 20 B, payload at offset 20).** `#d <blk> <cs> <ce> <hs> <he> <entry>` records it;
the load hands it back in the block window (4 bytes) so the caller does `W @ EXECUTE`. A phase must define and nothing
else at top level, and `tests/loader_tests.py` now seeds the phase **without** its trailing `RUNPH1` and dumps **before**
it ever runs: `cells at dump time [0,0,0,0,0,0]`, entry `1282`.

**Sealed-pointer refusal.** Op 3 checks the descriptor's code base against `mem[V_HERE]` and its header base against
`mem[V_SEAL]` before copying, and refuses with `REFUSED sealed pointers moved(...)` on a mismatch — so an image built
against a different seal can no longer be pasted at the wrong base. The resident checksum stays as the second line of
defence (a same-length body edit).

**`#l` is retired** and refuses by name: a console command writing `mem[]` while the REPL runs is passing by timing.

**Housekeeping regression (T8):** payload bytes are compared at offsets 0, 127, **128**, 300 and 500, so the
`BLK_SZ`(256) vs `blk_sz`(128) defect cannot return silently.

### Blocked: op 3 needs the request flag, and that costs 16 B

`repl_blk_req` is raised by the Forth **verbs** (`BLOCK`/`SAVE`/`PHASE`), not by `blk_xfer`, so a raw `n 3 BLKXFER`
pokes the mailbox and the host task never looks: measured on the chip as **status -3 (BK_NOSERVER)** with nothing
adopted. Raising the flag inside `blk_xfer` fixes it and was measured at **+16 B of pool** (7845 → 7861), i.e. **6 B
over the 7856 budget and 6 B over the ≤10 B gate**, so it was reverted rather than paid silently.

Three ways forward, for a decision:

| option | cost | note |
|---|---|---|
| raise the flag in `blk_xfer` | **16 B** of `.text` ⇒ application space 695 → 679 | simplest, works for every op; needs 5 B freed or `MEMSZ` lowered by 16 |
| publish `blk_out` (volatile) and have the host poll it | **~0 B, unmeasured** | the flag already exists and is already set/cleared correctly; making it volatile+exported is near-free, but it is a *protocol* change (the host would also service a late-timeout request) and needs its own measurement |
| wrap op 3 in a Forth verb that brackets the flag | 10–16 B | same cost class as option 1, plus a word |

Recommendation: measure option 2 first — it is the only one in the zero-byte class, and the case for a main-core loader
was that it costs nothing on the scarce side.
