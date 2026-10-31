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
