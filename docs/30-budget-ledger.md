# Budget ledger — what the 7 932 B wall costs, and what is left

Every number here is **measured** on this machine unless labelled **derived**.

## The wall is hard, not conventional

The ULP region is 8 192 B with a 260 B reserve, so **7 932 B** is the ceiling.
This is not a style rule: an 8 027 B measurement build (`MEMSZ 2 660`) was
flashed and **the board did not boot** — `cli.py` could not even open a
session. So no amount of `MEMSZ` raises the ceiling, and the ceiling is what
the App Store's phase window is subtracted from.

Shipping state: `MEMSZ 2 562` → image **7 931 B** (`riscv32-esp-elf-size`),
sealed phase window **995 B**.

## Tried for bytes, measured, and rejected

| lever | method | result |
|---|---|---|
| `-Os` for the ULP | `compile_commands.json` | already `-Os` twice (toolchain + appended) — no lever |
| disable more passes (`-fno-unroll-loops`, `-fconserve-stack`, `-fno-code-hoisting`, `-fno-gcse`, `-fno-if-conversion`, `-fno-crossjumping`, `-fno-tree-loop-distribute-patterns`, `-falign-*=2`, `-fno-reorder-blocks`, `-fno-shrink-wrap`) | `tools/measure.sh` twin | 7 937 baseline; `+4`, `+24`, `+8` — never smaller |
| **re-enable** the passes the CMake history disables (`-ftree-vrp -ftree-loop-im -ftree-fre -ftree-scev-cprop -ftree-forwprop -ftree-sink -fmove-loop-invariants -fssa-phiopt -ftree-pre`, and singles) | `tools/measure.sh` twin | 7 937 — identical, so the old tuning still holds with today's compiler |
| retire coprocessor probes | `nm --size-sort` diff vs the `MEMSZ 2 604` era | the only new functions are `P_slow` 22 B, `wr32.part.0` 26 B, `rd32.part.0` 22 B, `pl_hw.part.0` 28 B — **all of them the fix** (the alias gate and the wide 32-bit accesses are why pads move at all) |
| delete `pl_hw` | read the call site | `pl_hw(6,0,0)` is the **doorbell** (176 µs wake handshake), not a probe — must stay |
| registry state cells | `cli.py:registry_cells` | 29 cells, all used by apps; removing one drops an app |
| resident Forth words | `#k`, `Q`, `QH`, `GPIO@`… | objective says keep all Forth functionality — not removable |

## Two compactions that the machine refuses, with the reasons

1. **Filling the five card words into one `CARDS`** (4 headers = 12 B): refused,
   and named: `REFUSING: no interpret-state boundary inside one 92 B block from
   token 194 (':')`. The block loader caps a **single definition** at one 92 B
   block, so collapsing card words across several blocks cannot be uploaded.
   Folding `KJ KK KHL KENT` into `KEYDO` has the same problem: the folded body
   is one definition of ~130 B.
2. **`CD ( r c i st x -- )` sharing one helper across the label string**: the
   string has to print *between* `MARK` and `PAIR`, so a shared word would
   reorder output — the numbers would appear before the labels. Not a
   behaviour-preserving change, so not shipped.

## The route that is still open, and why it is the right one

`docs/26`'s own model is that **a program is a chain of phases**, one image per
phase, each at most the window. The shelf is currently **one** phase that
outgrows the window; splitting it (grid/labels in one phase, card state and key
dispatch in the next, chained through `NXT` the way calc already chains
`CALC1`→tape) costs **no pool bytes and changes no visible output**. That is the
legitimate fix, and it is app-store surgery: descriptors, chaining, registry
state, and it must be validated by `tests/appstore.py`'s 16 device checks, which
assert card drawing and key behaviour. It is where this work continues.

## Current truth of the two budgets

| requirement | state |
|---|---|
| image ≤ 7 932 B | **met** — 7 931 B measured, 1 B free |
| host suite | **met** — 30 PASS / 0 FAIL, oracle green |
| LoRa frame by the radio's own account | **met** — `SEND` = 1 (TxDone), `GetStatus` 0x2222, FIFO round-trip |
| outside receiver | **not met, and unreachable here** — only `/dev/ttyUSB0` exists; `lsusb` shows no SDR, no second radio, no `/dev/ttyACM*`. docs/29 records the same limitation for the C driver |
| App Store 16/16 | **not met** — shelf phase exceeds the 995 B window that the budget leaves; the phase split above is the fix |

## Continuation 5: the shelf was brought to 996 B, and the last byte has a name

Measured with the store's own refusal message (`996 B image is 1 B over the
995 B window`), single-caller folds inside the shelf phase are worth 4-12 B:

| fold | bytes | verdict |
|---|---|---|
| `OPND` into `OPEN` | 3 | valid (fits one 92 B block, no behaviour change) |
| `KENT` into `KEYDO` | 3 | valid |
| `WAIT` into `RUNSHELF` | 3 | **invalid** - nesting a counted loop is refused and the block upload reports NOTHING, so `RUNSHELF` silently did not exist |
| `COLR`/`COLL` into `KJ`/`KK` | 6 | **invalid** - `COLR`/`COLL` are not shelf-local: `examples/apps/sheet/sheet1.fs` uses them, so they are app vocabulary, not plumbing |
| `SLOTNO`+`FOOT` into `DRAW` | 6 | **invalid** - `DRAW` measured 95 B, over the one-block ceiling; `FOOT` alone fits (DRAW 80 B) and is valid |
| grouping five card words into `CARDS` | 12 | **invalid** - three cards per definition measured 122 B; two cards fit one block only if the definition stays on one line |

So the honest arithmetic is: 1 000 -> 996 B with two safe folds, then **1 B short**,
and the byte that would finish the job cannot come from the shelf without either
removing shared vocabulary or pushing a definition past one 92 B block. The
independent evidence that the *upload* is what refuses, not the radio: with the
folds applied the store reported `shelf: 996 B image is 1 B over the 995 B
window` - the first time the shelf was ever built, and it is a 1-byte problem
against a 995-byte window, not a 1 000-byte phase.

Two rules earned their keep again while doing this:
* `R1` (a `\` comment in a block source compiles as words) - my own GUARDRAIL
  prose poisoned the shelf phase exactly that way, and the screen drew 168 B of
  header and nothing else. Phase notes must use `( ... )`.
* `R21`-family ceilings are enforced by the *loader*, by name, and my checker
  reproduces the same 92 B measure before the board is asked.

The legitimate remaining fix is `docs/26`'s own model: the shelf becomes two
chained phases, which costs no pool bytes and changes no output. Because `RW`
rewinds before every phase, phases do **not** have to share the window with each
other - each one owns it alone - so a split is admissible and it is not a
workaround.

## Continuation 5b - the shelf does fit; the entry read hangs

With the valid folds plus `I1` (BAND's six repeated `NL INROW` collapsed into one word) the store
stopped refusing the shelf entirely: no `ERR_DICT`, no `996 B is 1 B over`, no `REFUSING`. The phase
compiled inside the 995 B window, and the build then failed at the *next* step -
`dev.num("' RUNSHELF .")` timed out, i.e. the coprocessor stopped answering while the entry xt was
being read. That is a new, narrower symptom (the same "board stopped answering after the program
exited" family the loader documents), not the window.

Two hazards were also caught this way, both mine:
* prose in a phase file poisons it twice over - a `\` comment compiles as words (R1), and a `(` …
  `)` note ends at the *first* inner `)`, so the rest of the note became code and the build reported
  `THAT?`, `FIT?`, `EXAMPLES/APPS/SHEET/SHEET1.FS?`. Notes about phases belong in docs, not in block
  storage. The file is back to the committed, verified text.
* removing `COLR`/`COLL` looked like dead plumbing and is not: `sheet1.fs` uses them.

State left verified: image 7 931 B / 7 932 B, suite 30 PASS / 0 FAIL, oracle green, radio still
reporting TxDone.
