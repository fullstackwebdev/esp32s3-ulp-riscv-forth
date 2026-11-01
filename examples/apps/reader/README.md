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
READ_ST + 0   page   0..7      (the page the top line is on)
READ_ST + 4   column 0..7      (the line within that page)
READ_ST + 8   mark   0..56     (the top line m wrote)
```

There is no `CREATE` in the phase (R16): the phase is replaced on every adopt, so a word it defined would vanish.
Entering the app re-adopts the phase, which reads these cells and resumes exactly where it left, mark included.

## Block arithmetic

```
page base = 80 + page*8                     (START is the app's literal inside its range)
screen line i = block 80 + RT + i,  i = 0..7
```

`RT` is clamped to `0..56`, so the window never runs past the end of a 64-line (8-page) document.

## Budget (measured, host engine at device geometry)

| item | bytes | how |
|---|---|---|
| display vocabulary (12 words) | **256** (220 code + 36 headers) | `SP ESC CSI M OFF INV CLR HOME DIGIT .N AT FILL` — duplicated from `examples/menu.fs`, per docs/26 |
| app logic (22 words) | **708** (640 code + 66 headers) | `NPG RMAX RT RSET RCLAMP RBLK RNEXT RPREV RMARK RGO RTTL RPN RTXT RALL RKEY RPOS RDRAW RGET KJK KMG KQ READ1` |
| **image** | **964** | code 862 + headers 102, measured as the `HERE`/`LATEST` delta around the file |
| window (docs/26) | 1022 | headroom **58 B** |
| source | 1739 B = **25 blocks** at 92 B | fsplit, `--phase` lint clean |
| cells | 3 | `READ_ST` |

The image number is a *host delta*: the suite's `artifacts/host_blk` is built at MEMSZ 1936 and holds the prelude in RAM,
so resident + phase does not fit there (`ERR_DICT`, 366 B free). The delta was measured on the same source at
MEMSZ 3000, where the dictionary has room; MEMSZ does not change the bytes a definition compiles to. The device figure
must still be re-measured by the integrator.

## Cost per keystroke (this is the app's real problem, and it is the machine's, not the code's)

A screen line is one block, and `BLOCK` is one mailbox round trip: **50.2 ms** median (CONSTRAINTS §2). Eight lines are
eight fetches, so one redraw of one frame costs **~400 ms**. Every key redraws. The alternatives cost more, not less:
buffering the page needs 8x128 B of RAM the window does not have (R16 forbids `CREATE`), and redrawing only the changed
line still needs the line's block, which means paying the fetch anyway — 50 ms instead of 400 for `j`/`k`, at the price
of a second draw path. That trade is left to the sequence's integrator, with the number attached.

## The allocation does not fit eight pages (contract vs machine)

`8 pages x 8 blocks = 64 blocks`. The reader's range in docs/26 (this branch) is **80..95 = 16 blocks = 2 pages**, and
the store itself ends at 128, so page 7 addresses blocks 136..143, which do not exist:

| page | blocks | what is there |
|---|---|---|
| 1 | 80..87 | reader content |
| 2 | 88..95 | reader content |
| 3 | 96..103 | **shelf's range** (96..111) |
| 4 | 104..111 | shelf |
| 5, 6 | 112..127 | launcher source |
| 7, 8 | 128..143 | **past the end of the store** — `BLOCK` answers `ERR_RANGE (-5)` |

`content/reader/p00..p07.txt` is authored for all eight pages because the contract asks for "page N of 8" and the text is
the deliverable. `tools/seed_pages.py` (BASE reader = 80) will refuse page 6 onward by name at block 128.

The page count is **one literal**: `: NPG ( -- n ) 8 ;` feeds both the title (`PAGE n OF NPG`) and the last top line
(`RMAX = NPG*8 - 8`), so running the two pages the allocation actually funds is `NPG` 8 -> 2 and nothing else in the
phase. That is deliberate, because the number in the title has to be the allocation's number; a second copy of it is a
stale constant waiting to happen. `tests/reader_logic.expected` pins the eight-page geometry (clamp 56, `label page8`),
so the flip also regenerates that golden - which is the point: the geometry change is visible in a diff.

## GUARDRAILs that could not live in the .fs

The phase source is split into 92 B blocks (`tools/fsplit.py`) and each block is interpreted on its own, so:

* **`tools/fsplit.py` is not comment- or string-aware.** A cut at 92 B can land *inside* a `( ... )` comment or a
  `." ... "` string; the next block then starts mid-comment and compiles the comment's words. Neither `fsplit` nor the
  linter's R10 catches it (an unknown first token models as "pops nothing"). Measured here: the first draft's second
  GUARDRAIL comment was cut, block 3 began with `GUARDRAIL - KEY returns -1 ...`, and the file was silently a different
  program. `read1.fs` now carries **one** comment block, under 92 B, at the top; anything else is in this file.
* **A `(` inside a `( ... )` comment ends the comment** at the first `)` — the rest of the line compiles as code
  (measured: `(1896)` in a test comment produced `LOOPS?`). No nested parentheses in a comment.
* **`."` eats one leading space.** `." OF 8"` printed `OF 8`, which left the title bar one column short of 70; the gap is
  now an explicit `SP`.
* **REGISTRY CELLS ARE 4 BYTES APART.** `READ_ST 1 +` addresses byte 1 *inside* the page cell, so the page reads back as
  `256 x` the value written and the column overwrites the page's high bytes (measured: `READ_ST @` = 1792 after storing
  0 and 1). `examples/apps/calc/calc1.wip.fs` uses `CALC_ST 1 + @` / `2 + @` throughout — it is parked and untested, and
  that idiom is why. Use `4 +` and `8 +`.
* **A `BEGIN..WHILE..REPEAT` written at top level, outside a definition, is wrong**: `BEGIN` and `WHILE` are immediate
  words that leave `HERE` and the branch operand on the *data* stack while the loop runs (measured: a counting loop
  printed `1896`, which is `HERE`). Loops belong inside a definition — all four in `read1.fs` are.
* **`BLOCK` returns an error CODE, not an address, when the fetch fails** (`-2` busy, `-3` no server, `-5` range,
  `-4` CRC). `TYPE` with a negative length/address walks memory, so `RTXT` tests `DUP 0 <` first and draws `ERR n`
  instead of a line. With page 3 and up pointed at other owners' blocks, this is what the screen will show.
* **`KEY` returns -1 for "no key"** and `RGET` tests it (R8); a loop that does not draws one frame per poll — 267
  frames/s measured on the board.
