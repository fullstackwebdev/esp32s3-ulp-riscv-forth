# 06 — The command-line REPL (requirement R8)

How you talk to the ULP's Forth from a shell on the workstation, over USB, with no Wi-Fi and no
Bluetooth.

**Status: implemented and working on the board.** `probe/repl/` is a byte-pump bridge on the main core plus
a REPL on the coprocessor; `probe/repl/repl` is the client. Measured transcript (E-047): `2 3 + .` → `5 ok`,
`: SQ DUP * ;` → ` ok`, `7 SQ .` → **`49 ok`** (a word compiled at runtime on the ULP), `BOGUS` → `BOGUS?`.

What is implemented is §2.1 (passthrough) and §4 (line discipline). Framed control frames (§3's `0x1D 'f'`)
and the `ulpctl` command set (§7) are **not** implemented; the ULP REPL does not yet handle the escape byte
itself, so `0x1D` currently reaches the line buffer as a non-printable and is ignored.

**Two terminal requirements, learned the hard way.** The ULP sends a bare `\n`, so the client must not clear
`OPOST|ONLCR` — `tty.setraw()` does, and the result is the staircase (every reply indented one more space).
`probe/repl/repl` re-enables output mapping after raw mode. In `picocom` the equivalent is
`--imap lfcrlf`. And a CRLF file must be stripped to `\n`, because `\r` and `\n` are both end-of-line to
the ULP and a CRLF therefore runs the line *and* an empty line (two prompts).

---

## 1. The chain

```
your shell                     ESP32-S3                            ULP
┌───────────────┐    USB    ┌────────────────────────────┐  RTC RAM  ┌───────────────┐
│ picocom       │ ttyACM1   │ bridge task (main core)    │  mailbox  │ Forth VM      │
│ ulpctl forth  │◄─────────►│  bytes in  →  cmd ring     │◄─────────►│ REPL task     │
│ (any terminal)│           │  bytes out ←  out ring     │           │ interpreter   │
└───────────────┘           └────────────────────────────┘           └───────────────┘
                                           ▲
                          ttyACM0 (native USB) = flashing / JTAG only
```

The main core copies characters. It never interprets Forth. Every character the ULP interprets has
been through exactly one ring on each side.

**Why the console is on UART0 (`ttyACM1`) and not the native USB (`ttyACM0`):**

| | native USB (`ttyACM0`) | UART0 via CH343 (`ttyACM1`) |
| --- | --- | --- |
| speed | 12 Mbit | 115200 default, higher available |
| flashing | shares the port with `esptool` | independent |
| tooling | needs our code or `idf.py monitor` | **anything**: `picocom`, `screen`, `minicom`, `cat` |
| 1980s feel | no | **yes** |

Putting the console on the plain serial line is what makes a dumb terminal work, and it removes the
"port busy while flashing" problem entirely.

---

## 2. Three ways to use it, one implementation

### 2.1 Passthrough (default)

The bridge starts as a byte pipe. Nothing is framed, nothing is buffered beyond the ULP's rings.

```sh
picocom -b 115200 --imap lfcrlf /dev/ttyACM1
```

You get the ULP's prompt, the ULP echoes your characters, `ok` appears per line. No history, no arrow
keys — the host does not edit anything, because in this mode there is no host-side tool.

### 2.2 `ulpctl forth`

Same pipe, plus a real line editor and one rule: **one line per prompt byte.** The tool sends a line,
waits for `ok\n`, then sends the next. That rule exists because P04 measured that an unpaced paste
loses 86–96 % of its bytes when the ULP is waking slowly.

```sh
ulpctl forth                     # interactive: history, backspace, no local echo
ulpctl forth prog.fs             # send a file, paced, stop on the first named error
printf ': SQ DUP * ;\n5 SQ .\n' | ulpctl forth -
```

### 2.3 Control frames

The same connection carries non-Forth commands: `peek`, `poke`, `monitor`, `load`, `run`. They travel
as escaped frames; ordinary console bytes are never framed.

---

## 3. Escape discipline

One control character is reserved: **`0x1D`** (Ctrl-]), because it is the convention users already
know from telnet and tmux, and because Forth source essentially never contains it (P10 measures the
rate over real source, expected 0).

| Sequence | Meaning |
| --- | --- |
| `0x1D 'f'` | switch the bridge to framed mode |
| `0x1D 'p'` | back to passthrough |
| `0x1D 's'` | bridge state: mode, ring occupancy, drops, last error (ASCII, one line) |
| `0x1D 'q'` | drop the ULP to autonomous mode and quit the session |

Rules that keep this safe:

* the escape is recognised **at any point in the byte stream, and before the XOFF gate**. P10 found
  that gating the reader on ring occupancy made an escape arriving after the watermark unrecognisable,
  which breaks `monitor` while input is flowing;
* exactly **one byte of lookahead**; a trailing `0x1D` is flushed as a literal after one poll, never
  swallowed;
* an unknown sequence after `0x1D` is emitted verbatim (both bytes), so a bad escape cannot eat
  text;
* **the console is printable ASCII only.** The ULP's line discipline ignores control bytes, so a
  literal `0x1D` can never enter a Forth line — there is deliberately no `0x1D 0x1D` escape. Binary
  payloads belong in framed mode's COBS body, not on the console;
* framed mode has its own framing (COBS + CRC-16 as in `02-harness.md`), so it cannot be confused
  with console text.

Measured (P10): `0x1D` occurs **0 times in 86.1 KB** of real and synthetic Forth source — the escape
is safe over source, and a hit requires a binary paste.

---

## 4. Line discipline

| Input | Behaviour |
| --- | --- |
| `0x20`–`0x7E` | buffered, echoed by the **ULP** (host local echo must be off) |
| `0x08` / `0x7F` | erase one character; echo `\b \b` |
| `0x0D` or `0x0A` | end of line, echo `\n`, interpret |
| other control bytes | ignored, not echoed, counted |
| line > 128 bytes | `ERR_LINE_TOO_LONG`, **line dropped**, dictionary unchanged — never truncated silently. The line buffer is **128 B, exactly the cmd ring size**, so a line can never be half-accepted: P10 measured the old 80-byte buffer against a 128-byte ring and found the mismatch produced errors that looked like ULP bugs |
| ULP not running / stale heartbeat | bridge replies `ERR_NO_ULP` instead of accepting input into a void |

Echo comes from the ULP, which means the echo you see is proof the characters actually arrived — a
useful property with no debugger available.

---

## 5. Flow control and latency

* Command ring 128 B, output ring 256 B (measured in P04).
* Above 75 % occupancy the bridge stops reading **data** from USB and reports `XOFF` in its state
  line — but it keeps parsing escape sequences, so control frames still work while the ring is full
  (P10 finding F2).
* **Paced** input (one line per prompt) never approaches that bound: a 79-byte line is 7 ms at
  115200, and the ULP drains it in one connected-mode wake.
* **Unpaced** input will be lost at the CH343/ULP boundary — P11 measures how much. `ulpctl` therefore
  paces by default and requires `--firehose` to do otherwise.
* Latency: connected mode wakes every 32–64 ticks = **207–414 µs** (P05's measured 6.46 µs per tick),
  plus one ring copy each way. Typing feels immediate; there is no visible lag to explain away.

---

## 6. Session lifecycle

| Event | Behaviour |
| --- | --- |
| `ulpctl forth` attaches | sends the mode frame, switches the ULP to the connected period (32–64 ticks) |
| idle 30 s, no input, no output | bridge drops the ULP to autonomous (100 ms) so the fast period is not burned for nothing |
| any keystroke after idle | back to connected on the next wake |
| terminal detaches mid-line | the partial line is discarded after the dead-man window; the dictionary is untouched |
| second opener | refused: `TIOCEXCL` plus an exclusive lock, message `port busy (held by pid N)` |
| ULP traps or halts | bridge reports `ERR_NO_ULP` with `wake_count` and `ip_shadow`, and stops accepting input |

---

## 7. Command set

```
ulpctl ports                     # what serial devices exist, and which one is the ESP32-S3
ulpctl forth [FILE|-] [--raw]    # interactive, file, or stdin; --raw = no line editing, no pacing
ulpctl monitor                   # heartbeat, cycles/wake, faults, overrun, drops (escape frames)
ulpctl peek ADDR [LEN]           # RTC memory, printed in ULP and host address space
ulpctl poke ADDR HEXBYTES
ulpctl load IMAGE.bin            # staged image, no reflash
ulpctl status                    # dict bytes used/free, tasks, fault counters, mode
```

Every command prints the port it used, and a failure names the opcode, the sequence number and the
elapsed time. A wrong port is a diagnosis, not a mystery.

---

## 8. What it costs

| Piece | Where | Rough size |
| --- | --- | --- |
| bridge task (UART driver, rings, escape, dead-man, lock) | main core, no ULP budget | ~350 lines C |
| `ulpctl` (framing, line editor, pacing, commands) | workstation, `pyserial` | ~450 lines Python |
| REPL state machine | ULP | already specced: `k=4`, 128/256 B rings (P04) |

Nothing here touches the 8176 bytes beyond what §4.3 already budgets.

---

## 9. Acceptance (R8 in `01-proposal.md`)

R8 is satisfied when all of these hold, each measured rather than asserted:

1. `picocom` alone gets a prompt and runs `: SQ DUP * ; 5 SQ .` → `25 ok`.
2. `ulpctl forth` sends 200 paced lines with `drops_out == 0` and zero lost input.
3. An unpaced 4 KB paste loses bytes, **and the loss is reported** (`drops_in > 0` with a count);
   the tool refuses to unpace unless asked.
4. A line containing `0x1D` round-trips verbatim; `0x1D 0x1D` produces one literal `0x1D`.
5. A second opener is refused with a named error and does not disturb the first session.
6. Detaching drops to autonomous within one dead-man window; re-attaching resumes with the dictionary
   intact.
7. `monitor` interleaved with `forth` on the same port does not corrupt console output.
8. A 129-byte line yields `ERR_LINE_TOO_LONG`, the line is dropped, and the dictionary is
   byte-identical afterwards.

---

## 10. Probes

Two, both in `docs/probes/`:

* **P10** (host) — line discipline, escape framing, flow control, and the false-positive rate of the
  `0x1D` escape over real Forth source. No board.
* **P11** (board) — the real link: attach latency, 200 paced lines, an unpaced paste, port exclusion,
  dead-man and re-attach, `monitor` interleaved with `forth`.
