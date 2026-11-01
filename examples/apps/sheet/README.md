# sheet — the spreadsheet phase (`sheet1.fs`, entry `SHEET1`)

One phase, one screen. State lives in `SHEET_ST` (below the seal); the 36 cell values live in the **block store**.

## Screen (70 x 24, docs/26 geometry)

```
row 1        inverse title "SHEET" + a "*" while the store is dirty
row 3        column letters  A    B    C    D    E    F      (pitch 5, first column 3)
rows 4..9    row numbers 1..6 at column 1, cells right-aligned in 3 columns at 3+5*col
row 11       SUM <value> - the current row's sum, shown by `s`
row 20       footer: the keys that work
```

The cursor is the cell drawn in inverse video (SGR 7 / SGR 0).

## Keys

| key | meaning |
|---|---|
| `h` `j` `k` `l` | move the cursor, wrapping (0-based cells: up from row 1 is row 6) |
| `0`-`9` | type the digit into the selected cell (replaces the value; cells clamp at 99) |
| `+` | add the cell above to the selected cell (row 1 has no cell above: no-op) |
| `s` | show/hide the cursor row's sum on row 11 |
| `w` | write the block back to the store (`UPDATE` then `SAVE`) |
| `q` | return to the shelf (`SHELF CHAIN`) |

Digits replace rather than accumulate: a cell is one digit or one `+` result, which keeps the
"what does this key do" answer to one line and needs no typing state.

## Store blocks

| block | use |
|---|---|
| **6** | the 36 values, one 16-bit word each, row-major: cell (r,c) is `2*(6r+c)` from the buffer address |
| 5, 7 | **never** - `srv_answer()` gives 5 no answer and 7 a bad checksum (`tests/blocks.fs`); an app on either cannot run on the host at all |

The values are one block because this machine has **one** block buffer and `BLOCK` refuses a different
block while the buffer is dirty - a per-row layout could not redraw a frame after an edit. The buffer
address is threaded on the data stack for the whole run: `6 BLOCK` once on entry, `W!` into that
buffer, `SAVE` on `w`.

## Registry cells (`examples/apps/registry.fs`)

`SHEET_ST` is **four 4-byte cells**: row at `SHEET_ST`, col at `SHEET_ST 4 +`, sum-shown at
`SHEET_ST 8 +`, dirty at `SHEET_ST 12 +`. `@`/`!` are word accesses on a byte-addressed store, so
`SHEET_ST 1 +` is a *misaligned address*, not the next cell - measured as one edit writing 1 at
`SHEET_ST+3`, after which row read back `16777216` and col `65536`.

## GUARDRAILs (the lessons this phase paid for)

* **A phase source cannot carry a comment.** `\` is R1 (a block has no line boundaries), and a
  `( ... )` comment is cut in half by `fsplit`'s 92-byte greedy fill - measured: 22 of the 63 blocks
  of the first commented draft were paren-unbalanced, and a block that starts mid-comment is
  interpreted as *code* on the chip. `examples/apps/calc/calc1.fs` has no comments for the same
  reason. The lessons therefore live here and in `probe/repl/tests/sheet_logic.fs`; the phase file is
  code only.
* **OFF is unconditional.** The inverse flag would have to survive *between* the two copies of the
  index that `OVER OVER` makes for the value address, and `OVER OVER` then reads the flag instead of
  the index - measured as every cell printing its own address. A redundant SGR reset costs 4 bytes
  of frame; a mis-stacked cell is a wrong screen.
* **`SAVE` without `UPDATE` returns 0 and writes nothing** (`p_blk_save`: `if (dirty == 0)
  { push(0); return; }`), so the dirty cell is set on every edit and cleared only when `SAVE`
  answers 0. A failed write therefore leaves the `*` on the title bar instead of being swallowed.
* **The wrap is one arithmetic step**: `(n + d + 6) /MOD 6`. This machine has no `DO`/`LOOP` and no
  `MOD`, and both rows and columns wrap at 6 - only the delta differs.
* **The row sum must read the same clamped values the cells show.** The store is not trusted:
  `W@` values are clamped to 99 on the way out, in the cell printer *and* in the sum, otherwise the
  screen shows 99s and a sum computed from 11050s.

## Budget (measured, host engine at device geometry with room to compile an over-window phase)

| group | bytes |
|---|---|
| drawing vocabulary the phase must carry (SP ESC CSI M OFF INV CLR DIGIT .N AT SENT) | 219 |
| number formatting (.9, .3, CLP) | 105 |
| title, letters, labels, footer, DSP | 231 |
| grid: address, position, cell, loop (CIO CXY CFLD GRID) | 156 |
| row sum (R3 RSUM SUM1) | 133 |
| cursor movement (MV MJK MHL) | 165 |
| store + edit path (CAT DRT DIG ABL TGL WRT KCM EDIT KEY1) | 313 |
| entry word (SHEET1) | 49 |
| **image = code 1 254 + headers 117** | **1 371** |

That is **349 B over the 1 022 B window** (docs/26). The sum feature is intact; nothing was deleted to
reach a number. See the lane report for the levers and their measured cost.
