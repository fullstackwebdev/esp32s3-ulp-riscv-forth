# 25 — A program library: resident launcher + behaviour images

`examples/menu.fs` is a resident launcher. `examples/demo_bars.fs` and `examples/demo_spin.fs` are *programs*: compiled
above the seal, dumped as behaviour images, and adopted at runtime. `./cli.py --library` builds the library and hands
the terminal to the menu.

```
./cli.py --library
```

Enter runs the selected program, `q` returns to the menu, `q` on the menu returns to the REPL. The tests are
`probe/repl/tests/{adopt_sum,programs,tui_cli}.py`, and `probe/repl/tests/device.sh` runs every hardware test in one
command under the board lock.

## Why the layout is the only one that can work

`BLKXFER` op 3 rewinds the dictionary and copies an image over it. **Any code that issues the adopt is inside the region
being replaced** — unless it sits below the seal. So:

```
52 ................ 1666   resident launcher (ANSI words, menu, RW, SWITCH, dispatch)   ← never replaced
1666 .............. 1822   adopted image: the selected program                        ← replaced on every switch
2020 .............. 2032   the image's headers, growing down from the seal
2032 .............. 2476   the RESIDENT header table (444 B)                            ← never replaced
```

Measured on the device (`tests/adopt_sum.py`, fresh boot): launcher 24 blocks sealing at 1 666, sealed `LATEST` 2 032,
bars image 156 B of code (4 blocks at 50), spinner 92 B (2 blocks at 60).

## Measured

| claim | number | how |
|---|---|---|
| adopt + first frame | **39–42 ms** | Enter → the program's own frame with its sentinel |
| returning to the launcher (`q`) | works | the image `EXIT`s back to the resident caller |
| menu → program (first switch) | works | bars, 11/11 `tests/programs.py` |
| menu → a *different* program after a switch | **works, 42 ms** | `tests/programs.py` "Enter → spinner (2nd program)" |
| the shipped command | 10/10 | `tests/tui_cli.py`, driven through a pty as the operator runs it |

## The guard that fired on ordinary use (fixed, measured)

`docs/25` first recorded this as an open defect:

```
img: REFUSED resident dictionary changed (sum 36586, built on …)
```

with the hypothesis that the checksum's tail `[sealed LATEST, top)` is rewritten by the preceding adopt. **The
hypothesis was wrong, and the measurement that killed it took one script and no firmware change**: snapshot `mem[]`
with `#m` (main core, zero ULP bytes), diff the snapshots, compute the sums host-side.

| snapshot | `[52,1666)` | `[2032,2476)` | total |
|---|---|---|---|
| after `#d 50` | 46 340 | 55 781 | **36 585** |
| adopt 50, adopt 50 again, adopt 60 | 46 340 | 55 781 | 36 585 |
| `1 SEL !` — what pressing `k` does | **46 341** | 55 781 | **36 586** → `REFUSED … (sum 36586, built on 36585)` |

The header area never moved. `[52, cs)` — the resident *code* region — also holds the launcher's **live cells**
(`SEL`, `q`, `qh`, `qt`, `qovf`, `brt`, `bh`, `bl`, `curblk`), and the menu writes `SEL` on every toggle. The guard was
refusing a dictionary that had not changed, in normal use. `SEL` sits at 1 180.

**The fix** (`main/repl_main.c`, one function, three callers): the resident sum now covers the **resident header table**
`[V_SEAL, blk_off)` and nothing else. Header entries are 3 bytes, `imm1 | xt11 | hash12` (P54), so that region still
pins every resident **name and the xt the image will call** — the only mismatch that makes an adopt execute garbage.
Pointer checks (`cs == vhere`, `hs+hl == vseal`) still catch a different layout.

**Tradeoff, stated rather than hidden:** a resident *body* edit that keeps every header and every length is no longer
detected (it was before, by accident, in the same sum that made the guard unusable). Detecting it would mean knowing
which resident bytes are mutable cells — the header table does not record that — and a body edit that keeps the
interface leaves a stale image perfectly callable.

**Verified in both directions**, because a guard nobody can trip is not a guard (`tests/adopt_sum.py`, 14/14):

| check | result |
|---|---|
| both images carry the same identity | 55 781 / 55 781 |
| adopt 50, adopt 50 again, adopt 60 | all status 0 |
| a live cell moves no identity | `SEL` 0 → 1, sum unchanged, adopt still 0 |
| a **forged** identity (`#p 60 13 …`) | `REFUSED … (sum 55781, built on 55782)`, nack 4 = `BK_CRC` |
| restoring the field | adopts again, status 0 |

## Bugs this feature found (all fixed)

1. **`EXIT` inside a called word returns from *that word*, not from the app.** The first dispatch used
   `IF … EXIT THEN` inside `KQ`/`KJK`/`KE`; the caller's trailing `DROP` then ran on an empty stack and the app died with
   `ERR_STACK` the moment any key was handled. Sub-words now return flags; the only `EXIT` lives in `RUNP`.
2. **`raw_skip_cr` ate the operator's first Enter.** The flag was armed by `!RAW` and cleared by the *next* CR — but the
   CR that terminates `!RAW` is consumed by the line parser, so the flag stayed armed. `tests/tui_menu.py` never noticed
   because its first key is `j`. The skip window is now 50 ms of ticks.
3. **`fsplit` cut `CREATE SEL 0 ,` in half**, so one block ended with a half-built `CREATE` and the next began with a
   bare `,` → `ERR_STACK` while compiling something else entirely. A `CREATE` is not finished until its `,`.
4. **`W` is not a firmware word** — it is `0 BLOCK` in a test fixture. `BLKXFER` already pushes the address the entry
   sits at, so a launcher uses that.
5. **`OVL` is `( blk -- )`, not a rewind**: it rewinds *and* loads a block, which arms source under running code. The
   pure rewind is two stores, and the writable cells are `VH`/`VL` — `HERE !` is accepted and ignored. **This one came
   back**: the shipped `cli.py --library` still used `2 OVL` to return to the seal (it happens to work from the console),
   and the test carried its own copy of the build, so nothing could catch it. The test now *is* `cli.library()`.
6. **The machine refuses a redefinition** (`: XX … ; : XX … ;` → `XX?`), so a resident name and a program's name must
   not collide: `50 CONSTANT BARS` in the launcher made the program's own `: BARS` fail two files away.
7. **`#c` compared the image's headers at the wrong address.** Code sits at `cs` and the headers at `hs`, which is *not*
   `cs + cl` (measured: code 1 666..1 822, headers 2 020..2 032), so `#c` read 12 unrelated bytes and reported
   "12 byte(s) differ" on a perfect image. A check that lies is worse than no check — it is read exactly when something
   else is already wrong.
8. **`--term`'s default word is `RUN`; the launcher's entry is `RUNP`.** `./cli.py --library` handed the terminal to a
   word that does not exist, and the machine printed `RUN?` into an invisible alternate screen. The tool looked hung on
   its own menu while it had not built one.

## The linter earned its keep

`: SWITCH ( desc -- ) 3 BLKXFER DROP W @ EXECUTE ;` was flagged as a leak — correctly: `BLKXFER` is
`( n op -- addr st )`, **two** results, so one cell leaked per switch and the launcher would have overflowed after
~14 switches. A launcher is exactly where such a leak hides: it works for the first few presses.
