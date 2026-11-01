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

## Block allocation (the store is 128 blocks; nobody may stray outside their range)

| range | owner | notes |
|---|---|---|
| 0–7 | reserved | descriptor packing experiment, never for app data |
| 8–19 | calculator | |
| 20–39 | spreadsheet | |
| 40–59 | mail | |
| 60–79 | gopher/browser | |
| 80–95 | reader | |
| 96–111 | shelf | |
| 112–127 | resident launcher source | `appstore.fs` upload |

A phase costs its **source** blocks (1–2) plus its **descriptor** blocks (`ceil((20 + image bytes) / 128)`, i.e. up to 10
for a maximal phase). So a maximal phase is ~11–12 blocks: **10–12 phases fit the store**, and that is the ceiling the
docs may claim.

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
