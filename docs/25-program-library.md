# 25 — A program library: resident launcher + behaviour images

`examples/menu.fs` is a resident launcher. `examples/demo_bars.fs` and `examples/demo_spin.fs` are *programs*: compiled
above the seal, dumped as behaviour images, and adopted at runtime. `tests/programs.py` builds the library and drives it
over the real TTY.

## Why the layout is the only one that can work

`BLKXFER` op 3 rewinds the dictionary and copies an image over it. **Any code that issues the adopt is inside the region
being replaced** — unless it sits below the seal. So:

```
52 ................ 1650   resident launcher (ANSI words, menu, RW, SWITCH, dispatch)   ← never replaced
1650 .............. 1788   adopted image: the selected program                        ← replaced on every switch
2026 .............. 2152   headers, growing down                                            ← replaced
```

Measured on the device (`tests/programs.py`, fresh boot): launcher 24 blocks, seal base 1 650, bars image 156 B of code
(5 blocks at 50), spinner 92 B (5 blocks at 60).

## Measured

| claim | number | how |
|---|---|---|
| adopt + first frame | **42–43 ms** | Enter → the program's own frame with its sentinel |
| returning to the launcher (`q`) | works | the image `EXIT`s back to the resident caller |
| menu → program (first switch) | works | bars, 5/5 runs |
| menu → a *different* program after a switch | **REFUSED** | see below |

## The open defect (named, measured)

After one program has been adopted and has returned, adopting a second one is refused:

```
img: REFUSED resident dictionary changed (sum 36586, built on …)
```

The image carries a checksum of the resident region so it can refuse to be pasted onto a dictionary it was not built
against — that guard is correct and it is doing its job. Its range is `[52, cs)` **plus** `[sealed LATEST, top)` (the
resident headers and everything above them), and the preceding adopt writes an image's own headers into that tail. So
the *first* adopt after a build matches and the *second* does not.

Not yet measured: which half of the range differs. The next step is to have `#d` print both partial sums and to
compare them after a switch, then decide whether the tail belongs in the resident checksum at all (a header edit that
preserves lengths is already detectable in `[52, cs)`).

**This is a named refusal, not a hang: nothing is pasted and the launcher keeps running.**

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
   pure rewind is two stores, and the writable cells are `VH`/`VL` — `HERE !` is accepted and ignored.
6. **The machine refuses a redefinition** (`: XX … ; : XX … ;` → `XX?`), so a resident name and a program's name must
   not collide: `50 CONSTANT BARS` in the launcher made the program's own `: BARS` fail two files away.

## The linter earned its keep

`: SWITCH ( desc -- ) 3 BLKXFER DROP W @ EXECUTE ;` was flagged as a leak — correctly: `BLKXFER` is
`( n op -- addr st )`, **two** results, so one cell leaked per switch and the launcher would have overflowed after
~14 switches. A launcher is exactly where such a leak hides: it works for the first few presses.
