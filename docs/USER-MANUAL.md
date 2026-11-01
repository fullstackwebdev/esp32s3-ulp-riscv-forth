# The 8 KB Computer — a user manual

You do not need to write code to use this. You need a terminal, a USB cable, and a sense of humour about
what fits in eight kilobytes.

---

## 1. What you are about to talk to

Inside your ESP32-S3 there is a small coprocessor called the **ULP**. It has **8 KB of memory** — about
eight thousand characters of this manual — and it keeps working when the main chip sleeps. On it runs a
**Forth** machine: a computer whose whole idea is that you type a word, and it does the thing.

Everything you will see on screen is drawn by *that* chip, one byte at a time, through the serial port.
Your terminal is just the glass.

There is also a bigger, faster chip in the same package doing errands for it: it holds a store of
**160 blocks of 128 bytes** in flash, so programs can be larger than the 8 KB and can survive a reset.

## 2. Start it

```
./cli.py                     Forth REPL (about 1.5 s to connect)
./cli.py --library           build the program library and open its menu
./cli.py -i app.fs           upload a program, compile it on the chip, then REPL
./cli.py -i app.fs --term    upload, then hand the whole terminal to the program
./cli.py -i app.fs --term RUN   ... and start it with the word RUN
```

### The program library (the launcher)

```
./cli.py --library
```

That compiles a **resident launcher** (25 blocks, sealed at 1 686) and two programs as images above the seal — colour
bars, 162 B, and a spinner, 222 B — then hands the terminal to the menu. The menu appears **~6.5 s after launch**:
2.3 s is a real hardware reset plus the freshness check, and 4.3 s is 34 blocks compiled on a 19 MHz chip one round trip
at a time (the build prints `compiling N/34 blocks` so it never looks wedged). `j`/`k` pick a program, **Enter runs
it** (35–43 ms, measured), `q` comes back to the menu, and **`q` on the menu ends the run** and gives your port back —
`--repl` stays in the REPL instead. Any program can be re-entered any number of times; the images live in the block
store and survive a reset.

**Leaving:** `q` on the menu ends the run and gives your port back (`--repl` stays at the prompt instead). `Ctrl-C`
always gets your terminal back *and* stops the program — it sends the app its own quit key and waits for the
interpreter's ` ok`, up to three times, because the menu runs the demo and each `q` leaves one level.

The bars draw eight rows of blocks, each in its own colour, and redraw on every key press. The spinner **rotates**
`| / - \` at about four frames per second (that is `MS 250` doing its job) with its phase number beside it. Both leave
on `q`, and the menu paints exactly one row red — the selected one. `MS` is a busy-wait on this machine: nothing else
happens during it, so keep sleeps short.

What makes it work: the code that *performs* the switch sits below the seal, so replacing everything above it never
replaces the caller. What it cost to learn: see `docs/25-program-library.md`.

Inside the REPL, lines starting with a dot are commands for your side, not the chip:

```
.help          what you can do
.term [WORD]   hand the terminal over (optional WORD is sent first, e.g. .term RUN)
.load FILE     upload another program without leaving
.status        blocks, erases, wear
.quit          leave
```

### The menu, right now (the single-app version)

```
./cli.py -i examples/tui_min.fs --term RUN
```

That uploads the 18-block app, the chip compiles it, and the terminal is handed over with `RUN` started.
`j` / `k` move the selection, `q` quits, and **Ctrl-C always brings your terminal back**. From inside the REPL
the same thing is `.term RUN`.

`examples/terminal_demo.fs` is the bigger app (five panes); it needs about 2 100 bytes of dictionary and the
machine has 1 366, so it currently stops with `ERR_DICT`. `tui_min.fs` is the one that fits.

`--term` gives the program a clean alternate screen and passes every keystroke straight through.
**Ctrl-C always gives your terminal back** - alternate screen, cursor and colours are restored even if the
program misbehaves, because a terminal left in the alternate buffer looks like a broken shell.

First run writes the app into the chip's flash-backed block store and asks the chip to compile it. You
will see a line like `44 blocks written and compiled by the chip.` That is not a download of a binary —
the chip is compiling Forth source you could have typed yourself.

Then press Enter and the app takes over the screen.

If it cannot find the board it will tell you what to check (cable; on Linux, `sudo usermod -aG dialout
$USER`). A different port: `PORT=/dev/ttyACM0 ./cli.py`.

## 3. The app

A full-screen terminal program, drawn entirely by the coprocessor:

* a title bar in reverse video,
* a menu you move through,
* a content pane that changes as you move,
* a footer with the keys.

`j` / `k` move, `Enter` refreshes, `q` quits and gives you your shell back. The app switches your terminal
to its **alternate screen**, so quitting restores whatever you were doing.

## 4. Type Forth yourself

Choose `3` in the menu (or use the plain console) and try, one line at a time:

```
2 3 + .
```
The machine pushes 2, pushes 3, adds them, and prints `5`. That is the whole language: words, left to
right, on a stack.

```
: DOUBLE 2 * ;
7 DOUBLE .
```
You just defined a word. It lives in the chip's dictionary until you reset it.

Colours and cursor moves are just bytes. `27` is ESC, so:

```
27 EMIT 91 EMIT 51 EMIT 49 EMIT 109 EMIT 72 EMIT 105 EMIT 27 EMIT 91 EMIT 48 EMIT 109 EMIT
```
prints `Hi` in red: `ESC [ 3 1 m` … `ESC [ 0 m`.

## 5. The rules of this small world

These are not suggestions; they are the machine's shape, and each one has bitten us:

| rule | why |
|---|---|
| **A typed line is at most 63 characters** | the input ring is 64 bytes; a longer line is refused whole, never truncated |
| **One definition must fit 92 bytes of source** | blocks are read in 96-byte passes |
| **One `LOAD` per line** | the rest of a line runs *before* the armed block, so two LOADs silently skip one |
| No `DO…LOOP`, no `CR`, no `SPACE`, no `MOD`, no `/` (use `/MOD`), no `>` (use `SWAP <`) | they are not compiled into this build; define them yourself if you want them |
| `BLOCK` always re-fetches | a same-block re-read without `SAVE` returns the stored bytes |
| Output is dropped, not queued, if the 128-byte output ring fills | a very chatty word can lose its tail |

## 6. Blocks, and things that survive a reset

A block is **128 bytes** of text or data. `N BLOCK` gives you its address; `UPDATE` marks it changed,
`SAVE` commits it, `LOAD` compiles it as Forth source.

```
0 BLOCK 2 + DUP @ 1+ DUP ROT ! UPDATE SAVE DROP
0 BLOCK 2 + @ .
```
That is a counter living in flash. Reset the board and it is still there. `#f` commits the cache and
reports how much was written; `#x` formats the store if you ever corrupt it (the machine refuses to lie
about it: it names the damage at boot).

## 7. When it goes wrong

| what you see | what it means |
|---|---|
| `WORD?` | that word is not in the dictionary — check spelling, or define it |
| `ERR_DICT` **from a block partway through an upload** | almost always a *stale* machine, not a big app: the reset silently did not happen and the new upload is compiling on top of the last one. `cli.py` now checks for a fresh dictionary (`HERE` ~786, >900 B free) and falls back to esptool; if it still cannot get one it tells you to replug. Measured: two runs in a row both report `fresh dictionary, 1366 B free` and compile clean |
| `ERR_DICT` with a fresh dictionary | the dictionary really is full: 1 366 bytes of new words is the whole budget |
| `ERR_STACK` | stack underflow; the line is abandoned, the session survives |
| `ERR_RANGE` | block number too large — the store serves **0…127** |
| `line too long` | over 63 characters; split it |
| screen looks cut off | the output ring dropped bytes; ask for less at once |
| silence | no board on the port, or the port is in use by another program |

## 8. Cheat sheet

```
2 3 + .            add and print
: SQ DUP * ;       define a word
9 SQ .             use it
0 BLOCK .          address of block 0
0 BLOCK 2 + @ .    a 32-bit cell in block 0
UPDATE SAVE DROP   commit a changed block
#f                 flush cache, report writes
#i                 store state: blocks, erases, wear, breadcrumbs
39 LOAD            compile block 39 as source
```

Welcome to eight kilobytes. It is more room than it sounds — and less than you'd like.

---

## Appendix: what the machine does *not* have (measured, not guessed)

| missing | work-around |
|---|---|
| `DO … LOOP`, `+LOOP` (`I`/`J` exist, but no loop opener) | `BEGIN … WHILE … REPEAT` |
| `CR`, `SPACE`, `SPACES`, `AGAIN`, `CASE`, `DEPTH`, `WORDS` | `10 EMIT`, `32 EMIT`, `BEGIN … 0 UNTIL`, nested `IF` |
| `MOD`, `/` | `10 /MOD DROP` |
| `>` | `: > SWAP < ;` |
| `KEY` that reads the line being typed | fixed: `KEY`/`KEY?` now read a **private keybox** the host fills with raw keystrokes (`!RAW` / `!LINE` switch the host between raw bytes and lines) |
| blocks above **127** | the server refuses them with `ERR_RANGE` even though flash holds 160 |

### Key facts for anyone writing an app

* A definition must fit **92 bytes of source**; `fsplit` refuses the rest.
* Blocks are read by `LOAD`, one per line — never two `LOAD`s on one line.
* The first frame of a full-screen app: `ALT HIDE CLR HOME …`, and always end with `NORM SHOW` so the
  operator's terminal is restored even if the user walks away.
* Single-slot keybox: a keystroke that arrives while the previous one is unread is **dropped**, not queued.

---

## For anyone writing Forth for this machine

Run the linter before you flash anything:

```
python3 probe/repl/tools/lint_forth.py examples/tui_min.fs
python3 probe/repl/tools/lint_forth.py --selftest      # proves each rule fires on the bug it came from
```

| rule | what it catches | the bug it came from |
|---|---|---|
| R1 comment | a `\` comment in a block source | a block has no line boundaries: `\ poll: …` compiled as the words `poll:` and `the` |
| R2 order | a word used before it is defined | `JK?`, `ACT?` at compile time |
| R3 underflow | a body that pops more than it holds | `DUP 106 = … 107 = … DROP` — the second comparison ate the key |
| R4 leak | a body that leaves items nobody wants | `ESC CSI 55 M` pushed the digit `'7'` and never emitted it: a cell per colour change |
| R5 loop leak | a loop body that is not balanced per iteration | `BEGIN KEY DUP 0 < 0= UNTIL` kept every `-1`, thousands per second |
| R7 byte range | an `EMIT` whose argument is not provably a byte `0..127` | `: DIGIT 48 + EMIT ;` — at n=897 that emits `0x81`, which the console reads as a **message code**: the spinner printed `ERR_BUSY`, then `ERR_ULPCODE` |
| R8 key -1 | a `KEY` that is never tested against `-1` ("no key") | `KEY DUP 113 =` treated "nothing" as a keystroke, so the demo ran at ~267 frames/s instead of once per press |
| ~~R9 ms stub~~ | **retired**: it said "`MS` does not sleep", which was measured true (20 × `200 MS` in 0.05 s) and is now false — `MS` busy-waits on the core clock (`100 MS` = +100 ms, `300 MS` = +301 ms). The rule was removed rather than kept as folklore. | — |

Declare stack effects and the linter can prove things: `: WAIT ( -- c ) … ;`. A definition without a declaration is
assumed `( -- )`, which is what most are. R7 needs that proof: `AND`/`/MOD` bound a value, arithmetic alone does not,
which is why `DIGIT` is `15 AND 48 + EMIT` and `.N` starts with `100 /MOD DROP`.

**Never write `\` or long comments inside `examples/*.fs`.** `cli.py` compiles the file verbatim (no comment stripping),
so a `\` line becomes words on the chip and a `( … )` that straddles a split boundary becomes words too. Write the
notes in the docs; the launcher, the bars and the spinner are all comment-free for that reason.
