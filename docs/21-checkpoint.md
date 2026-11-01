# 21 — Checkpoint: paging capabilities, before flash-backed storage

Tag: `checkpoint-paging-v1`. Branch `overlay-manager-enhancement`, merged to `main` in the same step.
Verified beside this doc: **host suite 24 PASS / 0 FAIL**, **capabilities 11/11 on the device**, and both re-run from a
**clean clone with a freshly flashed board**.

## The claim, in one sentence

**A program 5× larger than what fits the 8 KB machine runs on the chip, switching phases in about 50 ms, bounded by a
volatile 16 KB block store.**

## What is proven (tier: device unless stated)

| capability | evidence |
|---|---|
| 15 phases assembled and run from **binary images** | 15/15, each matching the host run of its own bytes: `p1 [8320,540800,0,65,128,0]` … `p15 [10112,798848,0,79,128,0]` |
| phase switch cost | **50 ms median** (min 44.7, max 58.8 over 200 loads) against **970 ms** for source loads — 19.4× |
| image size | 576 B payload = **5 blocks = 62 %** of the 8 source blocks (gate ≤ 65 %) |
| refusals | corrupt byte, resident-dictionary change, header collision, moved sealed pointers, stale request — each fires by name |
| block transport | 16 KB round trip, 0 mismatches; byte-exact at offsets 0/1/64/127/300/500 (covers the `BLK_SZ` vs `blk_sz` defect) |
| small-program win | 1 692 B paged vs 1 536 B control = **+10 %**, three phases (host) |
| REPL / on-device compiling | intact; images are a *cache* built by the on-chip compiler |
| host-side stack balance per cycle | identical overflow offset **(16,16,16,16,16)** over 5 cycles (host) |

## NOT proven — do not quote these as measured

1. **Stack balance at the end of the chip's dump/adopt loop.** Two probe attempts failed (underflow is silent; literal
   pushes never report overflow). Proven instead: 15/15 cycles complete and no window address is left on the stack. The
   *host* balance check above covers the logic, not the hardware.
2. **25 phases / 8.4×** — a prediction. Measured is **15 phases / 7 740 B / 5.0×**.
3. **Survival across reset** — the store is the host's `.bss`; a power cycle loses the program.
4. **The 586 ms age-bound proposal** — derived from a 200-load worst case (58.8 ms) and an *estimated* 845 ms ULP wait.
   The bound is **unchanged at 400 ms** pending approval.

## Known hazards for anyone using this

- **Silent stack underflow**: `POP` wraps and yields 0; only *overflow* raises `ERR_STACK`.
- **Literal pushes miss the overflow report**: it lives in the primitive dispatch tail, so a literal push can overflow
  silently. Push through a colon word to be told.
- **`BLKXFER` is `( n op -- addr st )`**: it pushes the buffer address *and* the status. Dropping only the status leaves
  `1808` per call on the stack and overflows after ~13 cycles.
- **One `LOAD` per line**: the rest of the current line is interpreted before an armed block runs.
- **Fixture blocks**: 5 is silent and 7 answers with a bad checksum on the host fake server; `SB` is 6.
- **Interactive lines are 63 bytes**; longer lines are refused by name.
- **An image is valid only against the exact resident dictionary** it was built on; the descriptor's resident checksum
  refuses the rest.

## Gate demonstration (a check that cannot fail is not evidence)

- `tests/capabilities.py --host --break oracle` → exit **1** (two phases made to share a signature).
- `tests/capabilities.py --break leak` → the "no window address left" check **fails** with `1808` on the stack (10/11).

## Clean-clone result (this is what "green" means here)

`git clone` of this branch into a fresh directory, no leftovers: host suite **24 PASS / 0 FAIL**, capabilities `--host`
**PASS**, board **freshly flashed** (`pool 7845/7856`), device half run *from the clone*: **11/11 PASS**.

Two portability bugs were found by doing it and are fixed: `tests/run.sh` never created `artifacts/` (a clean clone then
reported "0 PASS / 0 FAIL" — a green run of nothing), and `host_expect()` assumed `.auto/tmp` existed.

## What is next (not started)

Flash-backed storage, on a raw `esp_partition`: it adds persistence and a larger bound at zero ULP bytes, and it is what
would let a claim say *bounded by flash*. Only then is "unbounded" defensible. Then: a real suite (menu + editor +
calculator), and the user-guide update (loader, 50 ms switch, `BLKXFER` contract, silent underflow, 63-byte lines).
