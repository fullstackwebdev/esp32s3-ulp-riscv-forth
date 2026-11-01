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

## Three presentation defects, and the test that asserted titles instead of pixels

Reported by the operator, all real, all in `.fs`:

| what was seen | what the code did | why no test caught it |
|---|---|---|
| "it just says Bar" | `: BAR ( i -- ) DUP 1+ COL 5 2 AT …` — **every** bar at the same cell (5;2), and `FILLN` filled with **spaces**: eight invisible overwrites of one cell | the test asserted `b"BARS" in frame` — the title |
| "it counts to 10, then a progress bar `******`, then resets" | that *was* the spinner: a counter plus `P` stars, which reads as a progress bar | the test asserted `b"SPIN" in frame` |
| "I hit `j` and it turns red, then it stays red" | `MARK` emitted `1 COL` for the selected row and **nothing reset the colour**, so every row ever selected stayed red | nothing counted colour runs |

**The root cause is the same in all three: the tests asserted that a *title* appeared, not that anything was drawn.**
`read_until(b"SPIN")` returns at the title, so it certified a frame whose rest was broken — the same weakness that let
`ERR_ULPCODE` through (above). The tests now read **whole frames by their sentinel** and count content:

* every frame ends with `SENT` (a `0x00` byte) and the reader stops there — reading until a *title* desynchronises the
  stream, which was measured as "0 red rows" in a frame that had one, immediately followed by "2 red rows" in a frame
  that had one. `SENT` therefore belongs at the **end** of a frame; both demos had it after the title;
* menu: exactly **one** `\x1b[31m` per redraw, before and after moving — that is the operator's bug, in one assertion;
* bars: **144** `#` and **8** distinct colour codes;
* spinner: at least two of `| / - \` seen while idle.

## Chaining images as phases: the Forth way, measured

A program can be **several images**. One image is one phase and must fit the window above the seal; the whole program
need not. The mechanism is a tail call by variable — no descriptor change, no scheduler, no `.c`:

```
CREATE NXT 0 ,                                    \ the continuation cell (resident, below the seal)
: CHAIN ( desc -- ) NXT ! ;                       \ a phase's last act: name the NEXT phase, or 0
: ADOPT ( desc -- xt ) RW 3 BLKXFER DROP @ ;
: SWITCH ( desc -- ) NXT ! BEGIN NXT @ WHILE NXT @ ADOPT 0 NXT @ EXECUTE REPEAT ;
```

* the launcher hands `SWITCH` the **first** descriptor (what `PICK` does);
* `SWITCH` clears `NXT` before every `EXECUTE`, so a phase that says nothing **ends the chain** — the safe default;
* a phase that wants to continue ends with `62 CHAIN` — one token, and the value is the next descriptor;
* state shared between phases lives **below the seal** (`PA` is the counter the gauge increments): the window is
  replaced on every adopt, so anything a phase leaves there is gone.

### Measured on the device (`tests/tui_cli.py`, `60 SWITCH`)

| | |
|---|---|
| window above the seal | **290 B** |
| gauge: 3 phases | 100 + 112 + 188 = **400 B** = **1.38 × the window** |
| the chain | adopts 60 → 62 → 64 → ends, **152 ms** for all three, ends with "phases done" and the menu back |
| the price | every resident byte is a byte no phase can use — the launcher grew to 26 blocks and the window fell from 346 B to 290 B |

That last line is the real trade and the reason overlays were banked at a 690 B window: **the launcher and the phases
compete for the same RAM.** Chaining still wins where the program is bigger than the menu — which is the case that
motivated this.

### What the linter learned from this (two rules and one check)

| rule | catches | earned by |
|---|---|---|
| **R10 block start** | a *block* that begins with a word needing the stack | the `CONSTANT` split above — a block is a line and every line starts empty |
| **R11 fit** | a definition that cannot fit one 92 B block | two phases written at 94 and 96 B, found only once the chip was flashing |
| `cli.check_chains()` | a phase whose `N CHAIN` literal disagrees with the descriptor map in `LIBRARY` | the map was edited twice while this feature was written; a stale chain jumps to an unrelated image and says nothing |

### Still open (named, not hidden)
A **fourth** hop stalls: with a 4th image chained after the 3rd, the machine adopted 60, 62, 64 and then re-entered
phase 3's body at ~41 Hz with `blk_out` latched, `V_LOADB` 0 and 64 B of unread commands in the ring. A three-phase
chain is solid; the fourth hop is not, and the shipped library is three phases. Next question: whether the adopt is
being refused silently after two `EXECUTE` levels (the dump prints nothing) or the block layer latches on the third
rewind. Measured facts to start from: `#u` while it spins shows `blk_out 1 req 0 off 2476`, and `V_HERE 1762
V_LATEST 2023` — i.e. the dictionary is the sealed one, not the pasted one.

## The dispatcher-only launcher: 1 193 B of window, and the race behind every stall (measured)

The window is what the resident launcher leaves behind, so the biggest window comes from making the dispatcher the
*only* resident thing. `examples/boot.fs` is that launcher — `CHAIN`, `PICKX`, `SWITCH`, `GO` and two cells, 134 B of
code:

| | full menu launcher | dispatcher only |
|---|---|---|
| code | 1 714 B | **134 B** |
| headers | 168 B | **24 B** |
| **window** | **254 B** | **1 193 B** |

4.7×. And the chain runs: `tests/dispatcher.py` builds **24 generated phases** and requires every one to run and the
line to return — measured **24 hops, 739 ms, 30.8 ms per hop, counter = 24, no refusals**. That is "unlimited
chaining" in the sense that matters: **the count is bounded by the store (128 blocks), not by the design.** 24 phases
at 2 blocks each is 48 of 128 blocks.

### Why every chain stalled before this: one flag, sampled

`BLKXFER` is a mailbox handshake, and the HP serviced a request **only on a 0→1 edge it sampled**, once per FreeRTOS
tick (10 ms at `CONFIG_FREERTOS_HZ=100`):

```c
int fresh = out_now && !blk_out_prev;      /* "a request I happened to SEE arrive" */
```

A raw `BLKXFER` does not raise `repl_blk_req`, so if the ULP cleared and re-raised `blk_out` between two polls the HP
saw `1 → 1`, decided "not fresh", and **never serviced it**. The ULP then waited out `BLKWAIT` (~845 ms), returned
`BK_NOSERVER`, and *deliberately left `blk_out` set* — after which every adopt answered `BK_BUSY` instantly. The
launcher ignored that status and `EXECUTE`d whatever was in the block window: the "phase body re-enters at 41 Hz" we
chased.

Three changes, all measured, none of them a delay:

| change | where | effect |
|---|---|---|
| test the **pending level** `blk_out == 1 && mailbox[2] == 0` | HP (`.c`) | a missed poll can no longer lose a request — **0 ULP bytes** |
| publish `blk_out` **after** the mailbox words | ULP (`.c`) | a half-posted request can never be seen |
| keep polling 8 × 150 µs after a service (`hot`) | HP (`.c`) | the next chained request is ~100–300 µs away, not a tick |
| `PICKX` checks the status and returns `NOOP` | `.fs` | a failed adopt **stops** the chain instead of running stale bytes |
| the per-adopt `img: adopted …` line is behind `#v 1` | HP (`.c`) | it was 4.5 of the 5.1 ms a hop cost |

**30.8 ms/hop → 2.1 ms**, i.e. 24 hops in 50 ms instead of 739 ms, and `tests/dispatcher.py` now asserts the *latency*
(under 8 ms) so a tick wait creeping back fails the suite rather than being felt by a user.

`cli.connect()` also proves the block server answers a read before returning: the ULP is armed ~500 ms before the main
core creates the block task, so a caller could previously act while `blocksrv` did not exist yet.

### Hops are not free, and names collide

* **~2.1 ms per hop**, of which ≤1 ms is the HP's poll. A 24-phase program walks in 50 ms. Fine for staged programs,
  still wrong for per-frame work.
* **Phase names must not collide with resident names.** The dictionary stores a 12-bit hash and refuses a collision with
  the same `NAME?` a missing word produces: `: P1` was **refused** while `: PHASE1` compiled. With ~60 resident words
  that is ~2–3 % per name, and a paged design multiplies the number of names — so this grows teeth as phases multiply.

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
9. **The linter's own word table lied.** It listed `MOD`, `/`, `>`, `@!`, `ALLOT`, `CR`, `SD` and `SPACE`; the machine
   has none of them. It therefore linted a launcher containing `100 MOD` as CLEAN while the chip answered `MOD?` at block
   79. `tests/lint_vocab.py` now asks the device about all 60 names before every device run — a table that certifies
   itself certifies nothing.
10. **`pulse_reset` did not reset this board.** `: ZZZZ 1 ;` (HERE 794) then an RTS/DTR pulse left HERE at 794; only
   esptool's hard reset returned it to 786. The chip exposes USB-Serial-JTAG, whose DTR/RTS are emulated, so the modem
   bits are not wired to EN. Two no-op resets per connect were ~3 s of the 21 s `./cli.py` startup, and the failure
   reported itself as "the board did not come back to a fresh dictionary". Now verified and fell back automatically:
   **21.7 s → 2.9 s**, measured.

## The spinner flood: `ERR_ULPCODE`, and two bugs behind it (fixed, measured)

Reported by the operator, correctly: *clicking the spinner and getting flooded with `ERR_ULPCODE`*. Reproduced under a
pty, and the stream says the whole story in one line:

```
... \x1b[5;2H\x7f3  \x1b[5;2H\x7f4  ...  \x1b[5;2H<9  \x1b[5;2H=0  \x1b[5;2H=1
            0x7F        ERR_ULPCODE 0x80 ...     ERR_UNNAMED ...  0x91, 0x92, ...
```

The frame counter (`DUP 5 2 AT .N SP`) walks past 99 in four seconds, and the old `.N` was

```
: DIGIT ( n -- ) 48 + EMIT ;
: .N ( n -- ) DUP 10 < IF DIGIT ELSE 10 /MOD DIGIT DIGIT THEN ;
```

`EMIT` is the **raw byte** path, and `src/msg_codes.h` reserves everything at or above `0x80` for console messages
(`0x81`..`0x90`). A digit built as `48 + quot` walks straight through that space: at n=790 it emits `0x7F` (invisible),
at 800 it emits `0x80` → `ERR_ULPCODE 0x80`, at 810 `0x8A` → `ERR_BUSY`, at 825 `0x90` → `ERR_UNNAMED`, and from 0x91
on, `ERR_ULPCODE` for every frame, with the byte incrementing. Two bugs made it reach 800 in one second:

1. **`KEY` returns `-1` for "no key"** and both demos compared it only with `113` (`q`), so "nothing" counted as a
   keystroke and the draw loop ran flat out — measured at ~267 frames/s, not one per press.
2. **`MS` does not sleep.** Measured: twenty `200 MS` in **0.05 s**. `L_P_MS` is `pl_hw(3, POP(), 0)` and `pl_hw` op 3
   returns the wake count (`src/p31_cases.inc`, `src/ulp_p39.c`), so the pacing did nothing at all.

**Fixes in `.fs`:** `DIGIT` clamps its input (`15 AND 48 + EMIT`), `.N` proves its range first (`100 /MOD DROP
DUP 10 < …`), and the bars demo waits with the resident `K0` (which drops `-1`) instead of calling `KEY` itself.

**And one in `.c`, with permission:** `MS` now busy-waits on `rdcycle` instead of returning the wake count (F-125).
Measured after: `100 MS` = +100 ms, `300 MS` = +301 ms, slope x1.00, for **38 B** of the 8 192 B pool. So the spinner is
a *spinner* again — `FRAME STEP 250 MS KEY …`, 3.7 frames/s, 158 B/s — and the property that matters is the **rate**:
even if `MS` broke tomorrow, the counter is bounded and the digits provably legal, so the worst case is a fast spinner,
not a flood of message codes.

### What the tests did not catch, and now do
`read_until(b"SPIN")` returns the instant the title appears, so the old `tui_cli.py` certified a program whose first
frame was fine and whose second was `ERR_ULPCODE`. It now reads for a **fixed window after the first frame**, then
judges an idle screen by **rate** (2 s of spinner must be a handful of frames and under 3 000 bytes — a no-op `MS` sends
16 KB), with no `ERR_*` and no byte `>= 0x80` anywhere.

`tests/adopt_sum.py` also pins the **digits**: `0 .N` → `0`, `9 .N` → `9`, `99 .N` → `99`, `100 .N` → `0`. That check
exists because the first version of the fix printed `09` for 9 (`DUP 9 <` is false at 9) and **every device test passed
anyway** — none of them read the text.

## The linter earned its keep

`: SWITCH ( desc -- ) 3 BLKXFER DROP W @ EXECUTE ;` was flagged as a leak — correctly: `BLKXFER` is
`( n op -- addr st )`, **two** results, so one cell leaked per switch and the launcher would have overflowed after
~14 switches. A launcher is exactly where such a leak hides: it works for the first few presses.
