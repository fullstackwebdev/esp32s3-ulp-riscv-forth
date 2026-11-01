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
./cli.py
```

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
| `ERR_DICT` | the dictionary is full: 1 382 bytes of new words is the whole budget |
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
