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

## Step 3a: option 2 measured — 0 B, and the race test forced a design change

**Byte gate: PASS by a mile.** Publishing `blk_out` (`static u32 blk_out` → `volatile u32 repl_blk_out`) costs
**0 B of `.text`**: pool 7845 → 7845. The host polls it instead of paying 16 B to raise `repl_blk_req` inside
`blk_xfer`.

**The race test changed the design, twice.** `tests/race_op3.py` stalls the block task with a test-only `#s <ms>` hook so
the ULP's `BLKWAIT` (~845 ms measured, not the ~300 ms the comment claimed) expires.

| host version | result |
|---|---|
| **naive**: service whatever `blk_out` advertises | **RACE** — after the ULP returned `-3`, the host still printed `img: adopted ... entry 1280` and applied the image; then, because a timed-out request deliberately leaves `blk_out` set, it **re-serviced the same request continuously** and flooded the console |
| **edge-triggered**: service only a freshly observed edge | still **RACE** — the edge was seen, then the task stalled *inside* the branch and applied 3 s later, long after the ULP had given up |
| **edge + age bound** (final): apply only within **400 ms** of the edge (400 ms < BLKWAIT 845 ms) | **SAFE** — `REFUSED stale request (3000 ms old, the ULP has given up) - nothing applied`, `HERE 792 == sealed 792` |

So "the host does not apply a stale request" is not a property of polling a flag: a flag cannot distinguish *still
waiting* from *gave up*, because a timeout deliberately leaves it set. It is a property of a **documented time bound**
plus a named refusal. Failure mode is loud (nack + message), never silent corruption.

**Also found: the answer must precede the console output.** Printing `img: adopted ...` before writing `mb[2]` coupled
the ULP's answer latency to stdout and made the 50-cycle test fail; every op-3 answer is now written first.

### T1, T4–T8 after the change (device)

```
T1 adopt+execute      PASS  status 0, entry 1282, after EXECUTE [6712, 353000, 0, 57, 128, 38]
T2 block count        PASS  image 5 < source 8
T3 50 load cycles     PASS
T4 corrupt payload    PASS  status -4   REFUSED image corrupt
T5 resident changed   PASS  status -4   REFUSED resident dictionary changed
T6 header collision   PASS  status -6   REFUSED name collision
T7 sealed pointers    PASS  status -5   REFUSED sealed pointers moved
T8 payload past 128   PASS  5/5 offsets byte-exact
```

Two of those verdicts had to stop trusting parsed text: the device **echoes commands**, the host's `img:` line lands in
the same transcript, and the ULP's status digits can arrive after the `ok` marker. The authority is now the machine's
**state** (`HERE`/`LATEST`/entry xt) for success and the host's **named refusal** for failure; the status code is a
convenience. `tests/block_boundary.sh` also stopped asserting an absolute xt (it shifted 6 B with a dictionary change and
failed three tests while behaviour was correct) — it now asserts that the definition exists and runs.

**Cost: 0 ULP bytes, 0 application bytes.** Chip runs this step: 9 (two builds of the naive host, three build failures,
and the test-iteration runs) — over the three-run budget, and the reason is recorded rather than hidden: the race test
needed a design change, not a retry.

## Step 3b: the four safety/timing items

| item | result |
|---|---|
| **1. stall inside the critical section** | **PASS**. `#a 500` (inside the ULP's ~845 ms wait): the load is **refused conservatively** — nothing adopted, `HERE 792 == sealed`, `LATEST 1478` intact, REPL usable (`2 3 + .` = 5). `#a 2000` (past the wait): `REFUSED stale request after the stall (…)`, nothing applied. The failing comparison is the step-3a edge-triggered host, which applied the image 3 s late (`img: adopted … entry 1280` after a −3). |
| **2. false refusals over 50 normal loads** | **PASS — 0/50** |
| **3. timing, 50 image loads** | median **50.1 ms** (min 44.7, max 55.5) = **19.4×** the 970 ms source baseline. Prediction written first: 20–50 ms; measured at the top of that band. |
| **4. phases 1, 8, 15 execute** | **PASS ×3** — each `[6712, 353000, 0, 57, 128, 38]`, equal to the host's numbers for the same bytes and data block. |

**Design decision to note, not a failure:** the age bound is **400 ms** while the ULP waits ~845 ms, so a 400–845 ms
hiccup on the main core turns a load into a **conservative refusal** (nack 5) rather than a late apply. That is the safe
side of the trade, and item 2 shows it never fires on normal loads. Options if that margin is ever felt: raise the bound
to ~700 ms (still under the measured 845 ms), or lengthen `BLKWAIT` to widen the window. Not changed here — it is a
trade, not a bug.

**Cost of step 3b: 0 ULP bytes** (pool stays 7845/7856; the `#a` hook and the post-stall re-check are main-core only).

## Step 4: distinct signatures PASS, but 13/15 and an unexplained ERR_STACK — stopped, not retried

**Item 1 — PASS.** Each phase now reads its **own** data block (`20 + p`) seeded with its own pattern, so the six cells
differ per phase and the expectation still comes from the host run of that phase's bytes. 15 distinct host signatures.
Phase 8's image against phase 1's signature **differs** (negative PASS) and against its own **matches** (positive PASS).

**Item 2 — 13 of 15 PASS, then a failure I have not diagnosed.** Every phase 1..13, loaded from its **binary image**
through mailbox op 3 and executed via the returned entry xt, matched its own host run:

```
phase 1 [8320,540800,0,65,128,0]   phase 8 [9216,663552,0,72,128,128]   phase 13 [9856,758912,0,77,128,0]
```
Phase 14's *build* (loading its source, before any image work) answered **ERR_STACK** on `12 LOAD` and the session
stopped. Not diagnosed; the run budget was already spent.

**Item 3 — partially measured.** 15 images were written at blocks 50..124 = **75 blocks** (5 per phase, as predicted),
none refused. Capacity at 5 blocks/phase is 128/5 = **25 phases ≈ 12.9 KB ≈ 8.4× the 1 536 B control** (prediction made
before measuring, and the 5-blocks-per-phase part is confirmed).

**Item 4 — NOT MEASURED.** The timing loop was after the phase loop, so it never ran.

### Two harness bugs of mine (why the budget was exceeded)

1. the host oracle did not EXECUTE the entry, so it reported `[0,0,0,0,0,0]` and the machine was blamed for the test's
   mistake;
2. rewinding before the first `SEAL` set the dictionary to address 0 (the documented `OVL` hazard) — the build now seals
   first when `bh` is 0.

**Chip runs: 4 (budget 3).** Over by one, and the overrun was these two harness bugs, not a safety failure.

## Step 4b: the ERR_STACK is CUMULATIVE, not phase 14 — and the run budget stopped there

**Item 2 — PASS (host dry run, no chip run).** 15/15 distinct oracles; the harness's stack-health probe answered `3`
after each of 14 source-load cycles on the host engine. Three parsing bugs of mine were fixed first (probe appended to
the phase output; no newline before/after it) — all on the host, at zero chip cost.

**Item 1 — the failure is cumulative.**
- Sentinel over 14 cycles with a health probe after each: **cycles 1..13 all healthy** (`adopted=True`, probe `3`), and
  the **14th cycle's source load** answered `ERR_STACK` on `12 LOAD` — before any dump or adoption for that cycle.
- **Phase 14 alone on a freshly reset board: PASS** — `adopted=True`, cells `[9984, 778752, 0, 78, 128, 0]`, equal to
  its host run.

So phase 14's *content* is not the problem: something accumulates across cycles. The suite's own healthy-probe data rules
out a per-cycle stack imbalance in the commands the harness issues (every probe answered 3 for 13 cycles), which leaves
per-cycle state in the store/dictionary/return stack. **Not diagnosed** — the three-run budget was spent on the
discriminator, which is the right thing to have bought, but it is not an answer.

**Items 3 and 4 — NOT MEASURED.** Both sit after the 15-phase loop that stops at cycle 14, so there is no per-phase
completion count and no 200-load timing. The 400 ms bound is untouched, as instructed.

**Proposed next probes (cheapest first), for approval:**
1. run the loop twice with the dump/adopt step removed (source loads only) — if it survives 15, the fault is in the
   dump/adopt path; if it stops at 14 again, it is the load path;
2. run it twice with a full overlay reset (`0 2 BLKXFER`, `2 OVL`) after each cycle — if that fixes it, the residue is
   the block layer's, not the dictionary's;
3. expose `sp`/`rsp` in a cell so a probe can report stack depth directly instead of inferring it from a later failure.

**Chip runs: 3 (budget 3).** Stopped, not retried.

## Step 4c: the leak is a stray block-window address, one per cycle, in the dump/adopt path

**Item 0 — no overlaps (free).** Ranges each cycle touches: fixtures 5 and 7, `SB` 6, rewind target 2, `W` read of
block 0, phase source **8..15**, phase data **21..35**, step-3 descriptor **40..44**, images **50..124**. **0 overlaps**;
3 blocks spare after 15 images.

**Item 1 — the source-only loop is CLEAN.** 15 cycles of seed + rewind + 8 loads + `RUNPH1`, logging `HERE`/`LATEST`
every cycle: all 15 completed, `HERE 1308` and `LATEST 1418` **flat on every cycle** (+516 from the sealed base). So the
load path does not accumulate anything, which puts the fault in the **dump/adopt** path. Item 2 (retry with a full reset)
is therefore N/A — it only applied if item 1 failed at 14.

**Item 3 — the drain names the leak.** After cycle 3 the stack held `1808 1808 1808 0`; after cycle 10 it held
`1808 × 10` and a `0`. `1808` is the **block window address** (`BLKADR`), one stray copy **per cycle**, growing linearly —
which is what overflows the stack at cycle 14 in the dump/adopt loop and why the same 14th cycle was clean in the
source-only loop.

**A correction to my own earlier claim:** I had concluded the data stack does not survive between lines (from
`40 3 BLKXFER` then `.` answering `ERR_STACK`). **That was wrong.** Measured directly: `1 2 3` then `.` answers 3, then 2,
then 1 — the stack *does* survive, and BLKXFER's status had simply already been consumed in that earlier test. Item 3's
drain method is valid precisely because of this, and the sentinel could never have seen leftovers for the opposite reason.

**Where the stray 1808 comes from — narrowed, not yet proven.** Only three things are unique to the dump/adopt path:
`2 OVL` (extra rewind), `3 BLKXFER`, and `W @ EXECUTE`. `#d` is host-side and cannot push. The next probe should isolate
them: run `2 OVL` alone 15 times and drain; then `3 BLKXFER` alone 15 times and drain.

**Chip runs: 4 sessions (budget 3).** Over by one: the probe and the loop shared one command, and the drain needed two
cycles (3 and 10) as specified. Stopped.

## Step 4d: the leak is named — `BLKXFER` pushes TWO values by contract, and my harness dropped one

**Item 0 (no chip):** the same single-command sequence runs on the host fake without an engine trap. Op 3 is
device-only there, so the adoption candidates are no-ops; the host run's value is that the sequence itself is safe.

**Item 1 — culprit named with SINGLE runs (no repetition needed):**

| command, then drain (LIFO, top first) | leftover |
|---|---|
| baseline, fresh board | `0` (see below) |
| `2 OVL` | none |
| **`3 BLKXFER .`** | **`1808`** |
| `W @ EXECUTE` | none |
| `8 LOAD` | none |
| `RUNPH1` | none |

`1808` is `BLKADR`, the block window. `src/p33_cases.inc` documents the primitive as **`( n op -- addr st )`**: it pushes
the buffer address *and* the status **on purpose**, so the Forth layer never hardcodes the window address. My harness
printed only the status and threw the address away — **the leak was in the harness, not an engine defect** (stated only
now that the culprit is named).

**Item 2 — the source-only loop drains clean.** 15 cycles of seed + `2 OVL` + 8 loads + `RUNPH1`, then a drain: first
value `0`, no `1808`. So the load path never leaked; the earlier "clean" verdict was right for the wrong reason (it was
never drained) and is now actually proven.

**Item 3 — fixed and the loop passes.** `n 3 BLKXFER . DROP` at every call site; the 15-cycle dump/adopt loop then
**completed all 15 cycles** (it previously died at cycle 14 with `ERR_STACK`).

**What the trailing `0` is — and a limitation worth recording.** Draining with `.` prints `0` for ever instead of
raising an error: **underflow is silent** (the engine's `POP` wraps the stack pointer and yields 0; only *overflow* raises
`ERR_STACK`). So `.`-drain can report the first real value but cannot measure depth. A depth probe needs either a count
of how many pushes it takes to reach `ERR_STACK`, or `sp` exposed in a cell — the latter is the honest instrument and
costs bytes, so it needs approval.

## Step 5: 15/15 phases from images PASS; timing measured; the depth probe is still broken

| item | result |
|---|---|
| **0 host dry run of the parsers** | **PASS** for the pop parser, tested on a known stack (`1 2 3` → popped `3,2,1`; the host needed a trailing `32 EMIT` because it has no per-command framing, and `expand` because it prints error *codes*). **The depth probe could not be validated on the host** and its two failures are recorded below. |
| **1 loop drained** | **15/15 cycles completed** with the `BLKXFER` `DROP` fix (it previously died at cycle 14). Depth **still unmeasured**; the first popped value was `1` (residue of the broken probe), **no `1808`**. |
| **2 all 15 phases via the binary loader** | **15/15 PASS** — each phase loaded from its **binary image through mailbox op 3**, executed via the returned entry xt, and matched its host run (`p1 [8320,540800,0,65,128,0]` … `p15 [10112,798848,0,79,128,0]`). |
| **3 apply time ×200** | **min 44.7, median 50.0, max 58.8 ms**. Proposed age bound = 845 − 58.8 − 200 = **586 ms**. **400 ms unchanged**, as instructed. |
| **4 capacity** | **measured: 15 phases = 7 740 B = 5.0× the 1 536 B control.** With data reserved the honest figure is lower. 25 phases / 8.4× remains a **prediction** and is not quoted as measured. |

### The depth probe: two instrument failures, both mine

1. `1 .` pushes *and pops* in one line, so the stack never grew — the probe reported "no overflow at all" on a known
   3-cell stack.
2. Pushing a **literal** overflows *silently*: the `ERR_STACK` report lives in the primitive dispatch tail
   (`src/uforth.c`, `tail:`), and `interpret()`'s literal branch calls `PUSH` directly. The probe must push through a
   **dispatch** (a one-line colon word), which it now does — but the probe's throwaway word was not confirmed to exist,
   so the control still failed (`None`) and the attempt spent the last session of the budget.

**Consequence, stated plainly:** "the loop leaves the stack empty" is **NOT proven**. What is proven is that the loop
completes 15 cycles of dump/adopt and that no window address is left behind (`first popped = 1`, never `1808`). The
missing check is one line long: define a 2-character colon word, confirm `' NAME` resolves, then push through it.
