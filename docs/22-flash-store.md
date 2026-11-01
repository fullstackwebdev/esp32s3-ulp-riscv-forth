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
