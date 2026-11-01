# reader — read1.fs (phase READ1)

A paginated reader over the block store: page text comes from blocks, never from the compiled image.

## Keys (docs/26 vocabulary only)

| key | bytes | does |
|---|---|---|
| `j` / Down | `j` (106) | one line down |
| `k` / Up | `k` (107) | one line up |
| `m` | `m` (109) | mark: write the top line into `READ_ST` cell 3 |
| `g` | `g` (103) | go: read that cell and restore page *and* line |
| `q` / Esc | `q` (113) · 27 | `SHELF CHAIN` — the dispatcher adopts the shelf |

**Line scroll, not page turn, and the key map is why.** `j`/`k` are the only keys docs/26 gives to "next/previous *item*",
and the app's item is a line. One cell pair (`page`, `column`) then serves both motions: `RT` is
`page*8 + column`, `RNEXT`/`RPREV` step it by one and clamp, and the page number in the title bar is *derived*
(`page + 1`), so the title can never disagree with the text. A page turn would have been the same arithmetic with a
step of 8, but then the reader would have needed a third key pair for the one-line scroll that prose actually wants,
and `j`/`k` would have been unused.

## State (below the seal — this is what makes it "always on")

`READ_ST` is three cells, **4 bytes apart** (`CREATE READ_ST 0 , 0 , 0 ,`):

```
READ_ST + 0   page   0..1      (the page the top line is on)
READ_ST + 4   column 0..7      (the line within that page)
READ_ST + 8   mark   0..8      (the top line m wrote)
```

There is no `CREATE` in the phase (R16): the phase is replaced on every adopt, so a word it defined would vanish.
Entering the app re-adopts the phase, which reads these cells and resumes exactly where it left, mark included.

## Blocks

```
descriptor   48          (the allocation's durable 8 blocks: 48..55)
content      64..79      (two pages, 2 x 8 blocks)
START        64
page base    64 + page*8 (page 1 -> blocks 64..71, page 2 -> 72..79)
screen line i = block 64 + RT + i,  i = 0..7
```

`RT` is clamped to `0..8` (`RMAX = NPG*8 - 8`), so the window never runs off the document: the last top line is 8, whose
bottom row is line 16, whose block is 79 — the top of the content range. The page count is **one literal**,
`: NPG ( -- n ) 2 ;`, which feeds both the title (`PAGE n OF NPG`) and `RMAX`; a second copy of that number is a stale
constant waiting to happen.

## Budget (measured on `artifacts/host_app`, i.e. at device geometry)

`host_app` is built by `probe/repl/tests/build_host_app.sh` from `src/image.h`: MEMSZ 2604, TIBSZ 96, baked HERE 786 /
LATEST 2152. The numbers below are `HERE`/`LATEST` deltas around each file at that geometry, so nothing here is an
estimate:

| item | bytes | how |
|---|---|---|
| baked app space | 1 366 | `LATEST - HERE` at boot |
| app-store resident (registry + dispatcher) | 329 (272 code + 57 headers) | `registry.fs` then `appstore.fs` |
| **window left per phase** | **1 037** | measured; docs/26 says 1 022 from the same subtraction with a 344 B resident — 15 B apart, so the contract's figure holds |
| display vocabulary (12 words) | 256 (220 code + 36 headers) | `SP ESC CSI M OFF INV CLR HOME DIGIT .N AT FILL`, duplicated from `examples/menu.fs` per docs/26 |
| app logic (23 words) | 723 (654 code + 69 headers) | `NPG RMAX RT RSET RCLAMP RBLK RNEXT RPREV RMARK RGO RTTL RPN RTXT RALL RKEY RPOS SENT RDRAW RGET KJK KMG KQ READ1` |
| **phase image** | **979** | 874 code + 105 headers |
| headroom | **58** | 1 037 - 979 |
| source | 1 767 B = 25 blocks at 92 B | fsplit, `--phase` lint clean; staged, not durable |
| cells | 3 | `READ_ST` |

The test adds **zero** dictionary bytes (it defines no words), which is why it fits in the 58 B that are left: a `CK`
or `NL` helper would not have.

## Cost per keystroke (the machine's, not the code's)

A screen line is one block and `BLOCK` is one mailbox round trip: **50.2 ms** median (CONSTRAINTS §2). Eight lines are
eight fetches, so one redraw costs **~400 ms**, and every key redraws. The alternatives cost more than they save:
buffering a page needs 8x128 B of RAM the window does not have (R16 forbids `CREATE`), and redrawing only the changed
line still needs that line's block, so it saves 350 ms at the price of a second draw path. Left to the sequence's
integrator, with the number attached.

A failed fetch degrades harder than it looks, because the latch stays set (CONSTRAINTS §4): the first miss costs the
full `BLKWAIT` (`ERR_NO_SERVER`, then `ERR_BUSY` for every later call). Measured in the grid run below — line 1 reads
`ERR -3`, lines 2..8 read `ERR -2`.

## Gates run from this lane (no board)

* **lint**: `lint_forth.py --phase --use examples/apps/registry.fs --use examples/appstore.fs` — clean.
* **logic**: `probe/repl/tests/reader_logic.fs` + `.expected`, run by `tests/run.sh` on `artifacts/host_app` with the
  resident and the phase loaded ahead of it. It pins the page/line arithmetic (0..8), the clamp at both ends, the block
  address (64/71/72/75, last 79), the `/MOD` order, the three cells, and the bookmark round trip through `READ_ST`.
* **grid**: possible, at device geometry, with `tools/screen.py ../../examples/apps/reader/read1.fs --host
  artifacts/host_app --prelude ../../examples/apps/registry.fs --prelude ../../examples/appstore.fs --keys q --grid`:
  the title bar is exactly 70 columns ending in `PAGE 1 OF 2`, the text occupies rows 3..10, the footer row 22, and the
  run ends on `q`. The *content* cannot appear in a host grid (the host's block server serves blocks 0..3; content is
  64..79), so those eight rows draw the named errors instead — the error arm, not a golden.
* **not run**: anything on the board, and `tests/apps/reader.py`/`parity.py` (the integrator's G2/G4).

## GUARDRAILs that could not live in the .fs

The phase source is split into 92 B blocks (`tools/fsplit.py`) and each block is interpreted on its own, so:

* **`tools/fsplit.py` is not comment- or string-aware.** A 92 B cut can land *inside* a `( ... )` comment or a
  `." ... "` string; the next block then starts mid-comment and compiles the comment's words. Neither `fsplit` nor the
  linter's R10 catches it (an unknown first token models as "pops nothing"). Measured here: the first draft's second
  GUARDRAIL comment was cut, block 3 began with `GUARDRAIL - KEY returns -1 ...`, and the file was silently a different
  program. `read1.fs` therefore carries **one** comment block, under 92 B, at the top.
* **A `(` inside a `( ... )` comment ends the comment** at the first `)`, and the rest of the line compiles as code
  (measured: `(1896)` inside a test comment produced `LOOPS?`). No nested parentheses in a comment.
* **`."` eats one leading space.** `." OF 8"` printed `OF 8` and left the title bar one column short of 70; the gap is
  an explicit `SP` now.
* **REGISTRY CELLS ARE 4 BYTES APART.** `READ_ST 1 +` addresses byte 1 *inside* the page cell: the page read back as
  `256 x` the value written and the column overwrote the page's high bytes (measured: `READ_ST @` = 1792 after storing
  0 then 1). `examples/apps/calc/calc1.wip.fs` uses `CALC_ST 1 + @` / `2 + @` throughout — it is parked and untested,
  and that idiom is why. Use `4 +` and `8 +`.
* **A `BEGIN..WHILE..REPEAT` outside a definition is wrong**: `BEGIN` and `WHILE` are immediate words that leave `HERE`
  and the branch operand on the *data* stack while the loop runs (measured: a counting loop printed `1896` = `HERE`).
  Loops belong inside a definition — all four in `read1.fs` are. This bit the test file, not the phase.
* **`BLOCK` returns an error CODE, not an address, when the fetch fails** (`-2` busy, `-3` no server, `-4` CRC,
  `-5` range). `TYPE` with a negative address walks memory, so `RTXT` tests `DUP 0 <` first and draws `ERR n`.
* **`KEY` returns -1 for "no key"** and `RGET` tests it (R8); a loop that does not draws one frame per poll — 267
  frames/s measured on the board.
* **At device geometry a *test* line is limited too**: `host_app` is TIBSZ 96, so any test line over 95 characters is
  refused with `line too long` before it runs. `tests/reader_logic.fs` keeps every line under 95 for that reason.
* **`tools/screen.py --host` does not strip the fake block server's `SRV ` diagnostic** the way `tests/run.sh` does, so
  a host golden written by `--expect` would contain a driver line the board can never produce and host/device parity
  could never match. The reader's grid run is `--grid` only, and the suite filters `^SRV ` itself.
