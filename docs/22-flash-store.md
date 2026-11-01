# 22 — Flash-backed block store: outline, then implementation

Goal: move the 128-block store out of the HP core's `.bss` into a **raw `esp_partition`**, at **zero ULP bytes**, so a
paged program **survives reset** and the bound becomes the partition size instead of 16 KB of volatile RAM.

## Why (the two things it unlocks)

1. **Persistence.** Today a power cycle loses every image and every phase; the host-side seeder exists only because of
   that. With flash, an image built once is an artifact: build, store, reboot, run.
2. **A bound that is not RAM.** "Bounded by a volatile 16 KB store" becomes "bounded by flash". That is the only version
   of *unbounded* this project is allowed to say, and only after this lands.

Side effect: `static uint8_t blkfile[128][256]` (32 KB of HP `.bss`) disappears.

## Design

**Geometry.** NOR flash: 4 KB sectors, page programs, and bits only go 1→0 without an erase. So a 128 B block write is a
**read-modify-write of a 4 KB sector**. The store therefore keeps **one sector cache** (4 KB) with a dirty flag: reads
outside it come straight from the partition; a write to a different sector flushes the cache first.

**Layout.** Sector 0 = superblock, sectors 1..N = blocks, 32 blocks per sector at 128 B.

```
superblock (sector 0, 4 KB): magic "BLK1" | version | block_size | block_count | generation | crc32(header)
data      (sector 1.. ): block b lives at sector 1 + b/32, offset (b%32)*128
```

**Validity, not optimism.** `fs_init()` validates magic, version, geometry and the header CRC. Anything wrong is a
**named refusal** and every block operation then fails by name; `#x` formats deliberately. A corrupt sector must never
read back as zeros and look like an empty store.

**API** (`main/flash_store.c`, all HP-side, no ULP involvement):

| call | meaning |
|---|---|
| `fs_init()` | find partition, validate superblock; returns 0 or a negative named reason |
| `fs_read(blk, dst)` | byte-exact 128 B, from the sector cache when that sector is dirty |
| `fs_write(blk, src)` | RMW into the sector cache, marked dirty |
| `fs_flush()` | erase + program the dirty sector (batched: one erase per sector, not per block) |
| `fs_format()` | erase the partition, write a fresh superblock |
| `fs_block_count()` | geometry from the partition, not a constant |
| `fs_stats()` | bytes programmed and sectors erased, so write amplification is *measured* |

**Console.** `#b` (seed), `#d` (dump image), `#p` (poke), `#l`-replaced op 3 (adopt) all route through the API, so
seeding now **persists**. New: `#f` flush, `#x` format (both loud).

## Gates (each must be shown failing first where a failure is expressible)

1. **Persistence**: seed blocks, flush, **hard reset**, read back byte-exact — 0 mismatches. This is the whole point.
2. **Image survives reboot**: build an image, flush, reset, adopt *without reseeding*, execute, outputs match host.
3. **Corrupt superblock**: overwrite the magic, reset — boot refuses **by name**, and `#x` recovers.
4. **Write amplification**: bytes programmed and sectors erased for a 128-block fill, recorded (not estimated).
5. **Sector RMW correctness**: write a block, then a *different* block in the same sector, then read both — the first
   must still hold its data (the classic RMW bug).
6. **Capabilities unchanged**: `tests/capabilities.py` still 11/11, host suite 24/24.

## Risks, stated up front

- **Wear**: ~100 k erases/sector. Batching keeps one erase per sector per flush; `fs_stats()` reports it.
- **Power loss mid-flush**: a partially erased sector is detected by the superblock CRC only if it is sector 0; data
  sectors need their own validity. *Deferred*: the first version flushes on demand and at `#f`, and the boot check covers
  the superblock. A per-sector generation counter is the follow-up, recorded here rather than pretended.
- **Read latency**: flash reads are µs, irrelevant against a 50 ms phase switch, decisive only for a hot data loop.
- **HP core must be awake**: with `CONFIG_PM_ENABLE` off it already is; enabling PM later makes each miss a wake, which
  is what `docs/18` T2 must measure first.
- **Image/resident coupling**: unchanged and still guarded by the descriptor's resident checksum.

---

## Implemented and measured (branch `flash-store`)

**The store is now a raw `esp_partition`.** `main/flash_store.c` (+ `flash_store.h`), 0 ULP bytes, pool unchanged at
**7 845 / 7 856**. `blkfile[]` remains as a **cache** of the store so the 16 existing block indexes keep working, but every
write is committed (`blk_commit`), seeding persists, and boot loads the store from flash.

| gate | result (device) |
|---|---|
| **1 persistence** | **PASS** — seed, `#f`, **hard reset**, read back `[65, 77, 88]` identical. Write amplification recorded: `program+erase 4144 B, 3 sector erase(s), 2 flush(es)` |
| **5 sector RMW** | **PASS** — two blocks in the same 4 KB sector both survive a reset (`65, 66`) |
| **2 image survives reboot** | **PASS** — image built, flushed, **board reset**, adopted *without reseeding* (`img: adopted code 516 + hdr 60 from block 50, entry 1282`), and `W @ EXECUTE` printed `83205408000651280` = the host's `[8320, 540800, 0, 65, 128, 0]` |
| **3 corrupt superblock** | not attempted: it needs a raw sector write from the host; the refusal path exists (`fs_strerror` names magic/version/geometry/CRC) |

**This is the unlock:** a paged program **survives a reset**. Before this, every image died with the power and the host
seeder existed to refill a volatile array.

### Three bugs found by doing it (each GUARDRAILed at the site)

1. **`esp_partition.h` is its own component** on this IDF (`components/esp_partition/include`), not part of `spi_flash`;
   `COMPONENT_REQUIRES` needed it or the build stops on the include.
2. **`#f`/`#x` guards used `n > 2`**, but they are two-character lines, so they fell through to the ULP and answered
   `#F?` while the operator believed the store had been flushed.
3. **The image commit skipped the last, partial block** (`i2 < blk`): that tail lived only in RAM, so after a reset the
   loader refused the image with `image corrupt (sum 52400, descriptor 38479)` — a persistence bug that reads exactly
   like corruption.

### Console surface added

`#f` flush (prints bytes programmed / sectors erased / flushes), `#x` format (recovery from a refused store), and the boot
line `store: flash N blocks x 128 B` or `store: REFUSED <named reason>`.

### Still open in this design

Per-sector generation/validity (a torn *data* sector is only detected through the superblock today), wear accounting past
the counters, and moving `blkfile[]` out of RAM entirely (32 KB) — deferred deliberately: the RAM mirror is what made this
land without touching 16 call sites.

---

## Step 6: gate 3 and torn-flush measured; cost/accounting not measured

| item | result |
|---|---|
| **0 host dry run** | **PASS** — the torn-flush classifier, validated on known inputs: `OLD`, `NEW`, `MIXED` all classified correctly. |
| **1 gate 3, failing first** | **Shown failing**: a build with `FS_SKIP_VALIDATE` (accepts a damaged superblock) **did not refuse** after the magic was zeroed, and block 21 still answered `65` — an unvalidated store serving data. **Real build**: `#i` reports `store REFUSED superblock magic is not BLK1`, the REPL stays usable, and `#x` recovers (`format: ok, store empty`). |
| **2 torn flush** | **PASS over 20 interrupts** — after a reset fired mid-flush, the block read back as **OLD or NEW every time, never MIXED**. |
| **3 flush/erase accounting** | **NOT MEASURED** — my harness died inside `build_and_adopt` (`no number in reply to 'W @ .'`), so the 15-phase flush count and the wear estimate have no number. One more session would close it. |
| **4 host suite on the branch** | **PASS — 24 / 0.** `capabilities.py` (device, 11 checks) was **not re-run on this branch**: that is a fourth chip session and the budget was three. |

### A UX gap found, and fixed

The boot refusal is printed **before any tool opens the serial port**, so gate 3 initially reported "no store line" — a
refusal nobody can read is not a refusal. `#i` now reports the store's state (ok/refused + named reason + counters) on
demand, and `#f`/`#x` keep their roles (amplification, recovery).

### Deliberately unchanged

- **`blkfile[]` (32 KB RAM mirror) stays.** Removing it makes the size limit real rather than mirrored, but it touches 16
  call sites and changes the failure model — the operator has asked to discuss it before any change.
- Sleep not enabled, no ULP bytes added (pool 7845/7856 throughout).

---

## Step 6 close-out: BLOCKED on a hang introduced by flash commits (not merged)

The wear counters landed (per-sector, `#i` prints `erases/sector 0:n 1:n … | hottest`), and one design bug was fixed on
the way: the superblock generation was bumped on **every block write**, so every flush erased sector 0 as well as the data
sector — double wear for one commit. It is now bumped **once per flush**.

**Blocker (device, reproducible twice):** the first phase execution after a flash commit is wired into the block-write
path **never answers**. `W @ EXECUTE` returns **no output at all** — not an error, not a timeout code, nothing, for 15 s.
It appears only with the flash store in the write path; the same sequence passed 15/15 in step 5 with the RAM store.

Most likely cause, stated as a hypothesis and not a conclusion: `esp_partition_erase_range`/`write` from `block_task`
disables the flash cache while the console task and the ULP bridge continue to run, so the machine stalls. The fix is a
design decision (single flash-owner task, or bracket every flash op and keep the write path out of the block server), not
a patch to try twice.

**Consequences:** item 3 (erase counts per phase switch and per SAVE) is **NOT MEASURED**; item 4 (`capabilities.py`) is
**NOT RUN on this branch**; the merge is **NOT DONE**, because the brief's gate requires both.

**Chip sessions: 3 (budget 3).** Session 1 was lost to my own harness bug (test never defined `W`), 2 and 3 both hit the
hang. Reported, not retried.

### Decisions still waiting

1. Which task owns flash. Options: (a) all flash work in `block_task` with the console and seed paths posting to it,
   (b) flash work in a dedicated task, (c) keep flash writes out of the block server entirely (commit only from the
   console, `#f`), which preserves the current hazard-free path but loses "SAVE persists".
2. After that: wear numbers, `capabilities.py`, then merge with the exact wording *"a paged program and its images survive
   reset; size is still bounded at 16 KB."*

---

## Step 6c: diagnosis (3 chip sessions, budget exhausted) — hang is HP-side and survives until reset

**Instrumentation added (HP .bss, 6 words + 16×2 B counters, 0 ULP bytes):** breadcrumb before/after each flash call
(`bc 1..6`), durations for erase / write / superblock, and `esp_reset_reason()` — all printed by `#i`:
`info: bc 6 | erase 20592 us, write 13496 us, super 0 us | reset reason 1`.

| probe | observation |
|---|---|
| Flash durations | **erase 20.6 ms, write 13.5 ms** — orders of magnitude below the 15 s silence, so a cache-disable stall cannot explain it |
| One attempt, execute phase 1 | **No hang.** HP answered `#i`, ULP answered `2 3 + .` → `5 ok`, phase ran |
| Next attempt (`flash_wear`) | **Hang at `W @ EXECUTE`, zero output for 15 s** — no named error, so not the ULP's 845 ms timeout path |
| After that hang, next session | **No bytes at all** even for `bh @ .` — the console itself is gone; the wedge persists until an external reset |

**Which hypothesis the data supports:** the HP side deadlocks (or starves) and takes the console with it; it is *not* a
brief flash stall and *not* the ULP waiting (that path prints a named error). Most consistent: a resource held across the
flash call inside `block_task` that the console/ULP bridge also needs. **Not fixed, as instructed.**

**Harness lesson, third time asked for:** `tools/devio.py preflight()` now asks the device about every word the harness uses
(`' WORD .`) and aborts naming the missing word. Writing it cost two dry-run failures on my own *fixtures* — "last line is
numeric" and "a line of only digits" — because the device prints `52 ok` on one line. The fixtures are now verbatim
transcripts.

---

## Step 6c-iii: option (c) does NOT fix the hang — the hypothesis is disproved

Flash commits were removed from the block-task write path (the only path the ULP blocks on): a ULP write now marks the RAM
mirror dirty, and `#f` commits every dirty block before flushing. **The hang reappeared anyway**, at `W @ EXECUTE` on the
third phase of the capability run. So "flash inside the ULP's critical path" is **not** the cause; the defect is in the
block-write/execute path itself, independent of the store.

Capability run on option (c) before the hang (device): engine `2 3 + .` = 5 · application space **686 B** · blocks seed+read
byte-exact (0, 1, 64, 127) · phase source load+execute matches the host `[8320, 540800, 0, 65, 128, 0]` · descriptor v2 with
entry xt 1282 = live xt. Then the third `W @ EXECUTE` went silent, as before.

**Next probe (one session):** run the same workload against `main` @ `7135d0d` (no flash store at all). If it hangs there
too, the defect predates the flash work and belongs to the block-write path — which changes what the merge should contain.

Also fixed, harness-side: `#i`/`#u` answer with `info:` and return without an `ok`, so a call waited until timeout while the
answer was already in the buffer. `info:` is a marker now.

---

## Step 6d: the trigger is a flash WRITE, isolated by three device runs

| build | 15-phase workload | verdict |
|---|---|---|
| `main` @ `7135d0d`, no store at all | **15/15**, every phase executes | the defect is not in paging |
| flash branch, store present, **writes disabled** (`BISECT_NO_FLASH_WRITE`) | **15/15 twice** | the store, the boot read pass and the mirror are innocent |
| flash branch, writes enabled | hangs at phase 1–3, four times | **a flash write is the trigger** |

With the trigger narrowed to "a flash erase/program", the mechanism is still unexplained, and the observation that has to
be explained is the split: **HP console answers `#i`/`#u` while the ULP has gone silent**. A request log (last 16 serviced
requests: op, block, ms) is now in `.bss` and printed by `#u`; it would not fit in RTC memory — adding 192 B overflowed
`rtc_slow_seg` by 188 B, because the ULP pool owns that region.

**Branch is in a bisect configuration and must not ship** (`#define BISECT_NO_FLASH_WRITE 1`). Step 6d's next session:
re-enable writes, catch a hang, read the request log. Then the fix is expected to be the task split already proposed —
flash in a task that neither the ULP nor the console waits on.

---

## Step 6e: the spin leaves NO trace in memory — it is image code looping, not a store wait

Caught the hang twice with the request log and the cell dumper live. Facts, all device:

- `blk_out 0`, `req 0`, `V_STATE 0`, `V_LOADB 0` — **not** waiting on the store, **not** inside `LOAD`, **not** compiling.
- `cmd h403 t383` = **20 bytes of input pending** (exactly the `… 3 BLKXFER . DROP` line): the ULP stops consuming input.
- `wakes 1081 → 1081` over 2 s: the ULP **never returns to sleep** — it is inside one wake, spinning.
- Last serviced request 7 510 ms, `now` 16 150 ms: the HP answered everything asked of it and was then idle.
- **Two full memory scans 1.2 s apart: 864 cells, ZERO changed.** The loop touches no memory, emits nothing, and asks
  for nothing — so it is not `S1..S6` (those increment `idx` in memory) but an infinite branch/jump inside the ULP.

That last point is the useful one: a spin with no memory writes cannot be the phase's scan loops and cannot be
`blk_xfer`'s poll (which leaves `blk_out` set). It is execution flowing into a self-jump — i.e. the code being executed is
not the code that was compiled. On `main` the identical phase/library sequence passes 15/15, and on this branch with flash
writes disabled it also passes, so the corruption is tied to a flash write.

**Next step (cheap, mostly host):** verify what was actually pasted. The loader checks the image sum *before* the copy; a
sum recomputed over `mem[cs..cs+cl]` *after* the copy would name "the pasted code is not what the descriptor said" — zero
ULP bytes, and it turns "garbage executes" into a printed fact. Then compare that region byte-for-byte against the seeded
blocks on the host.

**Instruments added this step** (all HP-side, 0 ULP bytes): request ring of the last 16 serviced requests (`op/blk/ms`),
the ULP sys-vars (`V_STATE`, `V_HERE`, `V_LATEST`, `V_SEAL`, `V_LOADB`), the HP edge-detector view, `#m <addr> <n>` cell
dump, and `hard_reset_capture()` which keeps the ROM boot log by toggling EN while holding the port.

---

## Step 6f: ROOT CAUSE FOUND — and it was the harness, amplified by flash stalls

The ULP was **not** wedged by a flash write. The chain, every link measured:

1. `seed_many()` sent seed lines in one burst and accepted an ack by **prefix** (`seed: block N <-`), ignoring the byte
   count. Measured acks in a 10-line burst: **64/128, 116/128, 65/77 bytes, one line missing entirely**.
2. The reason bytes were lost: `seed_poll()` is the only UART reader and it stalls **~34 ms inside a flash erase**
   (measured 20.6 ms erase + 13.5 ms write). The 1 KB RX ring overflowed. Now 4 KB (HP RAM, 0 ULP bytes).
3. A short block compiles a short phase: image **135 B instead of 576 B**. `EXECUTE` then jumped past the pasted body into
   bytes that were never compiled — which is why the spin touched **zero memory cells**, asked for nothing and emitted
   nothing. Every earlier hypothesis (flash in the ULP's blocked path, a store wait, a `LOAD` spin) is dead.
4. The fix is on the host: seed in batches of two, **verify each ack's byte count**, retry, and refuse loudly. `step4`
   now raises `seed failed for blocks [...]` rather than building on a short store.

### Result (device)

- **15 phases from images, 15/15**, every image exactly 576 B.
- `capabilities.py` **11/11** — with a *strengthened* balance check: the old one asserted "1808 not in the reply", which
  passed on an EMPTY stack (`ERR_STACK`). The new one pushes a sentinel and measures the net change: **0 extra items**.
- `flash_persist.py` **3/3**: flush, byte-exact after hard reset, two blocks in one sector, image adopted and executed
  after reboot (`83205408000651280` = host).
- Host suite **24 PASS / 0 FAIL**.

### Wear (device, measured for the SOURCE path: re-seed + dump + adopt per switch)

`#f` after 15 switches: **68 sector erases, 52 flushes, 213 016 B programmed**; per-sector `0:1 1:25 2:13 3:10 4:8 5:1`
— hottest is **sector 1 with 25 erases**. At a datasheet-order endurance of 100 000 cycles per sector:

| switch rate | hot-sector erases/day | lifetime |
|---|---|---|
| 1/hour | 40 | ~6.8 years |
| 1/min | 2 400 | ~42 days |
| 1/s | 144 000 | **~17 hours** |

Caveat: this is the **source** path, which rewrites the whole phase through the store. A pure binary adopt was not counted
separately, and the dirty-sector cache + explicit `COMMIT` (next step) is what makes the fast rate survivable.

### Claim, exactly as far as measured

> A paged program and its images survive reset; size is still bounded at 16 KB.

`SAVE` alone does not persist — `#f` commits (option (c)).

### `#u` and `#v` (the block server's own instruments)

`#u` prints what the server has actually *done* — the last 16 serviced requests as `op/blk/ms`, the running total, the
ULP's `blk_out`/`blk_req` levels, the ring cursors and the wake count — plus `pending_ms`, the age of the request it is
working on (`0` when idle). It answers while the ULP is silent, which is the entire point: "the ULP never asked" and
"the HP never answered" look identical from the port.

`#v 1` turns the per-adopt line back on. It is **off by default** because at 115200 baud that 55-character line is 4.8 ms
of UART and the server cannot poll while it writes — it was 4.5 of the 5.1 ms a phase hop cost (`F-133`). Failures
(REFUSED, nack, `ERR_*`) are never gated: only the success line is.

### If the server is not there

The store, the cache and the block server are all main-core code; the ULP owns only a 128 B transfer window. With no
server the ULP gives **one** `ERR_NO_SERVER` after `BLKWAIT` (~845 ms) and then `ERR_BUSY` for every later block call
until `0 2 BLKXFER` (BLK_ABORT) or a reset — deliberately, so a late answer cannot be raced into the next request's
buffer. `BISECT_NO_FLASH_WRITE` keeps the server but makes every commit a no-op (RAM-only, nothing survives power);
`P33_NOPAGE` removes paging entirely. The full three-case table is in
[25-program-library.md](25-program-library.md#what-works-with-the-hp-switched-off-measured-three-cases).
