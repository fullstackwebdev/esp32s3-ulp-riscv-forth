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

## Screen geometry (ANSI TUI, 80×24)

```
row 1        title bar        inverse: "APP STORE" + right-aligned app/page state
rows 3..20   content          the shelf draws cards; apps draw their own content
row 24       footer           keys that work right now, and the last status word
```

Shelf = **6 cards, 3 columns × 2 rows**: card 24 wide × 7 tall, one blank row between columns and rows.
Card layout (drawn by the resident `CARD`):

```
+----------------------+     line 1  top border
| SPREADSHEET      [1] |     line 2  title, inverse; [n] = shelf slot
|                      |     line 3..5  live state, up to 3 lines
| sheet  B7  q3 12x8   |     line 6  live state (never a placeholder)
+----------------------+     line 7  bottom border
```

**No placeholder content.** A card's lines come from its app's registry cells (cursor, count, page). "TODO", "coming
soon", "demo" on a card is a test failure, not a style opinion.

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
