# 26 — The App Store: a shelf of always-on apps on a 1.2 KB window

**Status: branch `app-store`, contract only. Nothing here is measured until a test says so.**

The machine now pages: a dispatcher-only launcher leaves a **1 193 B** window per phase, a hop costs **2.1 ms**, and the
block store holds **128 blocks × 128 B = 16 KB**. That is enough for ~**10–12 maximal phases**, i.e. 4–6 apps with 2–3
screens each. This document is the contract every app is built against; if it is wrong, it is wrong in one place instead
of six.

## The one invariant that makes "always on" true

A phase is **replaced** on every adopt, so a phase may not own state. State lives in **registry cells below the seal**
(`examples/apps/registry.fs`), which survive every switch. Entering an app re-adopts its phase; the phase reads its cells
and resumes. "Always on" is therefore not a feature an app has to be careful about — it is the only thing the machine can
do, and the tests assert it (enter → move → leave → return → the position cell and the drawn bytes).

## Thin resident, fat phases (learned from lane R, measured)

The first version of this contract assumed "resident ~700 B → window ~1 000 B" and then put the **display vocabulary**
(`ESC`/`CSI`/`M`/`SP`/`AT`/`INV`/`OFF`/`CLR`/`HOME`/`.N`/`DIGIT`), `CARD` and the title bar in the **resident launcher**.
Lane R measured what that costs on the board:

```
app space (HERE 786 .. LATEST 2152)                      1 366 B   MEMSZ cannot grow: pool 7 847 / 7 856
registry + appstore (dispatcher + display vocab + CARD)   831 B   -> window 535 B
the calculator phase                                      695 B   (would need 1 526 of 1 366)
```

Every phase has to draw, so a fat launcher makes a thin window — exactly backwards. The rule is therefore:

> **Resident = the dispatcher (`CHAIN`/`NXT`/`RW`/`NOOP`/`UNLATCH`/`PICKX`/`SWITCH`/`GO`) plus the registry cells.
> Nothing else. Any word two phases both need is DUPLICATED in both phases.**

A phase is replaced on every adopt, so it has to be self-contained anyway — and that removes a whole class of problem: two
apps can never collide in the dictionary, and no lane has to negotiate a shared vocabulary. The price is ~120–160 B of
repeated drawing words per phase, charged to the **store** (16 KB), not to the window. RAM is what limits features; the
store is what limits the number of phases, and it has far more room.

Measured with this launcher (host engine at device geometry, `F-135`):

```
resident: dispatcher 158 B + registry cells ~177 B     335 B
window:   1 366 - 335                               1 031 B
of which  the phase's own display vocabulary         ~175 B   (ESC ESC CSI AT .N ... - paid per phase)
          strings and layout                          ~90 B
leaves    for the app's logic                        ~760 B
```

So a phase's *own* budget is ~760 B of logic, not 1 031 B, and **that is the number to design an app against before writing
it**. A phase that does not fit gets its features split across phases — not deleted. `cli.py --library` refuses an
over-window image, but it can only do that once the program compiles far enough to be measured, which is too late to
design with.

## Screen geometry (ANSI TUI — **70 columns, the launcher's own constant**)

**The machine never asks the terminal how big it is.** There is no `ioctl`/`COLUMNS` anywhere in `cli.py` or the tests, so
the only width that exists is the one the launcher draws to: `examples/menu.fs` has

```
: FILL ( -- ) 0 BEGIN DUP 70 < WHILE SP 1+ REPEAT DROP ;      ( 70 columns )
: HDR0 ( -- ) CLR HOME 1 1 AT INV FILL ;                     ( a 70-wide inverse bar on row 1 )
```

70 is therefore the number the App Store must use — an 80-column layout would leave a ragged edge on the launcher's own
header and could not be verified against it. **24 rows** is the harness's assumption for a golden (a normal terminal),
not a machine fact; the launcher must never draw below row 24 and must not depend on rows it cannot see.

```
row 1        title bar        70-wide inverse bar (HDR0), right-aligned app/page state
rows 3..9    card band 1      3 cards across
rows 11..17  card band 2      3 cards across
row 20       footer           keys that work right now + the last status word
```

Card = **22 wide × 7 tall**, three per band: `22*3 + 2 gutters = 68` of the 70 columns.

```
+--------------------+     row 1  top border
| SPREADSHEET    [1] |     row 2  title, inverse, [n] = shelf slot
|                    |     row 3  first live line
| sheet B7           |     row 4
| q3  12x8           |     row 5
|                    |     row 6  (never a placeholder)
+--------------------+     row 7  bottom border
```

**No placeholder content.** A card's lines come from its app's registry cells (cursor, count, page). "TODO", "coming
soon" or "demo" on a card is a test failure, not a style opinion.

## The screen harness is NOT new

`tests/tui_cli.py` already drives a full-screen program and reads frames: it opens a **pty**, runs `cli.py … --term`
inside it, and reads until the **`SENT` sentinel (`0x00`)** that every frame ends with — `read_until()`, `dwell()`,
`frame()`. That is the reader; two lessons are already baked into it (a frame has an end, or you cannot count inside it;
and a reader that stops at the first match cannot see a flood that starts after it).

So the App Store adds **one** thing on top: a projection of the already-read frame into a 70×24 cell grid, because "the
card in slot 3 shows `B7`" is a cell assertion and counting escape bytes cannot say it. Rules:

* `tools/frames.py` — the **only** frame reader (moved out of `tests/tui_cli.py`, which imports it from there).
* `tools/screen.py` — grid projection + `--expect` golden diff, **importing** `frames`, never re-implementing the read,
  the pty, or the lock.
* An uninterpretable escape sequence or a byte ≥ 0x80 is **fatal and named**, never guessed into a grid that happens to
  match a golden.
* `tests/parity.py` — the genuinely new piece: same program and keys on the host binary and on the board, all cells
  diffed, and a **skip is never success**.

## Keys (the only vocabulary; every screen obeys it)

| key | bytes | meaning |
|---|---|---|
| `j` / Down | `j` · `ESC [ B` | next item / scroll down |
| `k` / Up | `k` · `ESC [ A` | previous item / scroll up |
| `h` / Left | `h` · `ESC [ D` | previous shelf column / previous page |
| `l` / Right | `l` · `ESC [ C` | next shelf column / next page |
| Enter | `13` | open the selected card / confirm |
| `q` or Esc | `q` · `27` | leave the app, back to the shelf |
| `n` / `p` | | page forward / back inside an app |

Escape alone (27) vs an arrow (27 91 65) is distinguished by reading the queued next byte; the keybox delivers sequences
intact (measured, `docs/25`).

## File layout (each lane owns its directory and nothing else)

```
examples/apps/registry.fs        the cell allocation. INTEGRATOR ONLY - lanes read it, never edit it
examples/apps/shelf/shelf1.fs    the shelf screen (phase)
examples/apps/calc/*.fs          calculator phases
examples/apps/sheet/*.fs         spreadsheet phases
examples/apps/mail/*.fs          mail phases
examples/apps/gopher/*.fs        gopher/browser phases (local hypertext, no network)
examples/apps/reader/*.fs        reader phases
examples/appstore.fs             resident launcher: dispatcher + CARD + GRID + key dispatch + registry
tests/apps/<app>.py              the device test: keys in, grid out, cells asserted
tests/apps/<app>.host.txt        the host golden (24x80 cells, exactly as drawn)
```

**One phase per file.** A phase file defines exactly one entry word (the file's name uppercased, e.g. `CALC1`) and may
**not** `CREATE`/`VARIABLE` anything (R16). It ends by setting `NXT` (usually `SHELF CHAIN`) so the shelf comes back.

## Block allocation (the store is 128 blocks — corrected by measurement)

The first version of this table did not add up: it gave mail 20 blocks and asked for 5 pages of 8 blocks (40) plus two
phase descriptors (~16). Lane MAIL measured the contradiction and was told to report it rather than shrink the content,
which is exactly right. The principle the arithmetic exposes:

> **Descriptors are durable — one per phase, `ceil((20 + image + headers) / 128)` blocks, 8 in practice.
> Source blocks are TRANSIENT — a phase's source is only needed while `cli.upload` and `#d` are staging it, so every
> phase shares ONE scratch range at the top of the store.**

| range | owner | durable? |
|---|---|---|
| 0–4 | reserved (descriptor packing, never content) | – |
| 5, 7 | **TEST FIXTURES, never allocate**: block 5 is silent, block 7 answers with a bad checksum (`srv_answer()`, used by `tests/blocks.fs`) | – |
| 6 | **sheet data**: 36 cell values in one block (`6 BLOCK` … `UPDATE` … `SAVE`) | yes |
| 8–15 | calc1 descriptor | yes |
| 16–23 | calc2 descriptor | yes |
| 24–31 | sheet1 descriptor | yes |
| 32–39 | mail1 descriptor | yes |
| 40–47 | gopher1 descriptor | yes |
| 48–55 | reader1 descriptor | yes |
| 56–63 | shelf1 descriptor | yes |
| 64–79 | **reader content**: 2 pages | yes |
| 80–103 | **mail content**: 3 pages (p00 list, p01–p02 bodies) | yes |
| 104–119 | **gopher content**: 2 pages (home + article) | yes |
| 120–127 | **staging**: the source of ANY phase is uploaded here, then `#d` writes its descriptor in its own range | no |

Rules that follow: a phase lives in the range of its *descriptor* (that is what `GO` chains to); the staging range is
reused by every upload and must never hold anything a phase needs at run time; content ranges never move, because page N is
`START + N*8` arithmetic.

### A cell index is a MULTIPLE OF FOUR (and the host will not tell you)

There is no `CELLS` word. `MAIL_ST 1 + @` is "the cell at byte +1", which is an unaligned 32-bit load: legal on the host,
a trap on rv32 (`F-136`). Write `MAIL_ST 4 +`, `MAIL_ST 8 +`; `C@`/`C!` are bytes and are fine. Linter rule **R19
alignment** flags a literal offset that is not a multiple of four, and the host is not an oracle for this - the chip is.

### A phase that draws a whole screen in one burst loses its tail (`F-137`, open)

The output ring is 128 B and a full screen is ~600 B. The device frame is correct for the rows and then ends; the footer
never arrives. Until that is fixed, treat a full redraw as a known limit: draw row by row (the ring drains between rows)
or draw only what changed.

### `>` does not exist on this machine, and the host server now answers the whole store

* Only `<` exists (`p31_prims.inc`): a clamp is written with the operands swapped, e.g. `2 MAX <`, never `MAX >`.
* The host fake server answered blocks **0..63** and the App Store puts content at 64..119, so every content read on the
  host took the no-answer path and `screen.py` exited 3 on the ignored request. It answers **0..127** now (block 5 still
  silent, block 7 still a bad checksum). Consequence: a test that wants "nobody answers" must name a silent block, not
  rely on being past a limit - `tests/loop.fs` used `99 OVL` and now uses `5 OVL`.
* A `( ... )` comment is not code: the linter blanks comments before scanning for definitions *and* before collecting a
  base file's vocabulary, so a GUARDRAIL that quotes `: W ... ;` no longer reads as a definition (lane MAIL had to write
  colon-free comments to stay lint-clean). Stack declarations are still read from the original text.

### Two store blocks belong to the test harness

`srv_answer()` in `probe/repl/src/uforth.c` gives **block 5** no answer at all and answers **block 7** with a bad checksum;
`tests/blocks.fs` depends on both. Allocating either of them means the app cannot be exercised on the host at all - it
`ERR_CRC`s on every run - so it would reach the board with zero pre-board evidence for its data path. Lane SHEET caught
this after my table handed it block 7.

### Writing a block back: three steps, and the second one is the trap

```
7 BLOCK        ( -- addr )   read the block into the buffer
... C! ...     poke bytes into that buffer
UPDATE         ( -- )       mark it dirty        <-- REQUIRED
SAVE           ( -- st )    write it back, 0 = ok
```

`p_blk_save` begins `if (dirty == 0) { PUSH(0); return; }` — so **`SAVE` without `UPDATE` returns 0 and writes nothing**.
An app that forgets `UPDATE` reports success on every keystroke and loses its data on the next entry, with a green test.
The same class of trap governs descriptors: `#d` plus a power cycle needs `#f` (measured by lane R). Any logic test for
stored data must assert a poke → `UPDATE` → `SAVE` → re-`BLOCK` round-trip, not just that nothing errored.

**One phase per app, and a view is not a capability.** The store is exactly full at 7 descriptors, so a second phase is
never free: it costs 8 blocks that have no home. A *view* (inbox vs message, page vs search results) is a cell and a
branch; a *capability* that needs its own compiled code and must survive a switch is a phase. Two lanes hit this in the
same way - mail asked for a viewer phase and gopher for a search phase - and both answers were the same: drive the view
from a registry cell. The one deliberate exception is the calculator, which the table funds with two descriptors because
splitting it is the thing that proves a multi-phase app works.

## Registry cells (below the seal; `registry.fs`)

```
SHELF_ST  cursor page             CALC_ST  mode tape
SHEET_ST  row col page dirty      MAIL_ST  msg page unread
GOPH_ST   page back fwd match     READ_ST  page col mark
APP       current phase desc      APP_PG   page within the app
SHELF     96   CONSTANT           SHELF_DESC is the literal 96 used by every return path
```
Names are capitalised with an app prefix so the 12-bit hash cannot collide across apps; `tools/hashsearch.py` is run over
the union of the app vocabularies before a wave is merged.

## The interface every lane codes against (measured, current)

```
resident:  examples/appstore.fs (dispatcher, 8 words) + examples/apps/registry.fs (cells)
           measured 344 B  (284 B code + 60 B headers)
window:    1 366 - 344 = 1 022 B
per phase: ~1 022 B minus its own drawing vocabulary (~175 B) and strings (~90 B)
           => ~757 B of LOGIC per phase. Design to 700 and measure.
```

* `SHELF` is a resident CONSTANT = **96**: every screen returns with `SHELF CHAIN`; the dispatcher does the adopting.
* A phase never calls `SWITCH`/`GO` - it sets `NXT` (`SHELF CHAIN`) and returns.
* A phase never owns state (R16): position, page, selection, counters live in `registry.fs` cells.

### Content format (pages are pages)

| concept | rule |
|---|---|
| page | **8 consecutive blocks**, one block per screen line |
| line | up to **70** characters, space-padded (the store fills with spaces) |
| page base | `START + page * 8`, where `START` is the app's own literal inside its range |
| authoring | `content/<app>/pNN.txt`, one line per block, ≤70 chars, ≤8 lines - seed with `tools/seed_pages.py` |
| link (gopher) | a line starting with `>` - its target page number follows immediately |
| list item (mail) | line 1..7 of page 0; Enter on the selected line opens page `1 + index` |

Blocks per app come from the allocation table; a 4-page document is 32 blocks.

### Two gates a lane can run WITHOUT the board

1. `lint_forth.py --phase --use examples/apps/registry.fs --use examples/appstore.fs <phase>.fs` - clean.
2. `tests/<app>_logic.fs` + `tests/<app>_logic.expected` - the pure logic (addressing, paging arithmetic, formatting) as
   words, run by the existing host suite. A `tests/apps/<app>.py` grid test comes next for screens that need no block
   content; anything that READS the store is verified on the board by the integrator, not claimed by the lane.

### Lane hygiene (learned from a lane that ran `find /`)

Every path a lane needs is known and inside its own worktree: `probe/repl/tools/lint_forth.py`, `probe/repl/tools/screen.py`,
`probe/repl/tests/build_host_app.sh`, `probe/repl/tests/run.sh`, `examples/apps/registry.fs`, `examples/appstore.fs`. A lane
that searches the filesystem for them has already lost the time it was trying to save - `find /` is banned by this
project, and `grep -r` from the repo root walks `probe/results/` and `.auto/tmp/` clones. Scope every search to the files
the contract names.

## Demo it

```
./cli.py --appstore              build resident + all five phases, seed content, open the shelf
./cli.py --appstore mail         the same, but only the mail app (the shelf is always built - it is the entry word)
```

Measured by that command on the board: calc **995 B**, tape **641 B**, mail **910 B**, reader **973 B**, shelf **1 026 B**,
all against the 1 037 B window, descriptors 8 / 16 / 32 / 48 / 56, content seeded and flashed.

**The screen on the chip is not yet demo-able:** the shelf draws ~1 KB in one burst, the output ring is 128 B, and the
frame's HEAD is lost (the visible result is a screen shifted up by several rows). That is `F-137`, still open. The same
build renders correctly on the host, which is the demo to show today:

```
cd probe/repl
python3 tools/screen.py ../../examples/apps/shelf/shelf1.fs \
    --prelude ../../examples/apps/registry.fs --prelude ../../examples/appstore.fs \
    --content mail --host artifacts/host_app --entry RUNSHELF --keys 'jj' --grid
```

## Wave 2 status (measured, 2026-11-01)

| app | files | image | window | state |
|---|---|---|---|---|
| **shelf** | `shelf/shelf1.fs` | 1 021 B | 1 037 B | merged; 6 cards, live values from cells, refuses the empty slot |
| **calc** | `calc/calc1.fs`, `calc2.fs` | 995 / 643 B | 1 037 B | merged; two phases chained 8 <-> 16, arithmetic proven by `calc_logic` |
| **mail** | `mail/mail1.fs` + 3 pages | 826 B | 1 037 B | merged; **on the board**: title, heading and both messages match the host grid |
| **reader** | `reader/read1.fs` + 2 pages | 979 B | 1 037 B | merged; 58 B headroom, `SENT` added so a frame has a boundary |
| **sheet** | `sheet/sheet1.fs` | **1 371 B** | 1 022 B | **over by 349 B, reported not hidden**: every feature present, parked like the calculator draft, wave 3 splits it |
| **gopher** | – | – | – | lane timed out with no files; it did independently find the alignment trap (F-136), which is why that fix went in |

Every phase is lint-clean under `--phase` with the registry + launcher as `--use` vocabulary, and the host suite runs four
new logic tests (`calc_logic`, `sheet_logic`, `mail_logic`, `reader_logic`) plus the corpus.

## The five gates — every app passes all of them, in this order

| gate | artefact | fails when |
|---|---|---|
| **G0 spec** | feature list + budget table (code B, blocks, cells) in the lane's report | a feature has no budget line |
| **G1 lint** | `lint_forth.py` clean (R1–R12 + R16, R18) | any finding |
| **G2 host** | `tests/apps/<app>.py --host` produces the golden | one drawn cell differs |
| **G3 anti-slop** | checklist below | any item |
| **G4 device** | the same test against `/dev/ttyACM1` | host ≠ device |

**Build-time refusals (integrator, in `cli.py`):** a phase image larger than the declared window, or a phase set that
would pass the store budget, fails the build — not the board.

## Anti-slop checklist (each item is a test)

1. Live data only: every card line and every screen field comes from registry cells or stored blocks.
2. No draw-once demos: enter → move → leave → return restores position (asserted).
3. Data is stored, not compiled in: sheet cells, mail bodies and gopher pages come from blocks.
4. Every screen returns to the shelf with `q`/Esc; no reset required (R18).
5. Every feature in the app's G0 list is exercised by its test; unexercised code is deleted, not documented.
6. One palette, box-drawn cards, no rainbow ANSI, no emoji, no centred nonsense.
7. Every claim in the docs has a test that fails when the claim is reverted (the R12 lesson).

## Waves

* **Wave 1** — contract code (`cli.py` budget + geometry, linter R16/R18), the harness (`tools/screen.py`,
  `tests/parity.py`, a host binary at device geometry), and the calculator as the reference slice that proves the
  registry end to end.
* **Wave 2** — shelf + spreadsheet + mail, in parallel worktrees, then gopher + reader.
* **Wave 3** — hardening: any device-only error becomes a linter rule or a host/device parity fix **before** the next
  app is written.

Lanes report, always: features → budget table → G2 golden → G4 device result → **any linter/parity gap found**. That last
field is how the loop feeds itself.
