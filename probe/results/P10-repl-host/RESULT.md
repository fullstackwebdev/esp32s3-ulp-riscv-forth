# P10 — REPL line discipline, escape framing and flow control (host)

Host-only probe (`gcc`, no board). Everything below is executed output, in this directory.
`probe/uforth/` and `docs/` were not edited; the interpreter was copied here and changed in the copy.
`probe/results/P03b-retry-progress/` was neither read nor written (it is excluded by name in
`measure_esc.py`).

---

## 1. Answers

### 1.1 The record table the brief asks for

| Item | Measured |
| --- | --- |
| `0x1D` occurrences in real + synthetic corpus | **0** in **86.1 KB** (22.6 KB real + 63.6 KB synthetic) → **0.000 / KB**, **0.00 per 10 KB** (fail threshold was > 1 per 10 KB) |
| escape table: sequences correct | **6 / 6** |
| line discipline: cases correct | **7 / 7** (plus a bonus split-refill case) |
| XOFF round trip | **0 bytes lost** (198 offered, 198 accepted, 198 pulled, in order, no duplicates) |
| double echo | **none** (out is byte-for-byte the ULP's echo) |
| suite | **58 passed, 0 failed** — both in `probe/uforth/` and in this copy |

### 1.2 The deciding question: is `0x1D` a safe escape?

Yes, and not marginally. Over every `.fs` file in the repo (10 files, 23 095 B) and a 2000-line
synthetic corpus written in `boot_min.fs` style (65 081 B): **zero occurrences**, `0.000/kB`.

The stronger statement is structural, not statistical: all 11 `.fs` files are pure printable ASCII
(checked explicitly — no byte outside `\t \n \r` + `0x20..0x7E`). `0x1D` is Ctrl-], which no keyboard
produces by accident and no text editor writes. A real occurrence therefore requires a *binary* paste
into the line buffer, which is not source text. Rate over source is **0**, and the design margin is
infinite within text — the failure criterion (> 1 per 10 KB) is not remotely approached.

### 1.3 What the escape table does, measured

| Sequence | Result |
| --- | --- |
| `0x1D 0x1D` | exactly one literal `0x1D` enters `cmd[128]`; the ring holds 1 byte, `out` untouched |
| `0x1D f` | `mode = framed`; **0 bytes** reach the ring; **0 bytes** out |
| `0x1D p` | `mode = passthrough`; 0 bytes in, 0 out |
| `0x1D s` | one ASCII line in the out ring (`mode=… cmd=n/128 out=n/256 drops=0 xoff=… accepted=… refused=…`), exactly one `\n`, ULP buffer and cursor untouched |
| `0x1D q` | quit flag set, drops to autonomous, 0 bytes to the ring; mode untouched |
| `0x1D x` (unknown) | **both** bytes verbatim into the ring, in order (`0x1D`, `'x'`) — nothing eaten |

Bounded flush: a `0x1D` at the end of a burst is held as **one byte of lookahead** and flushed as a
literal at the **first poll whose source is empty** — the bound is *one bridge poll* (one byte time on
the wire at 115200 ≈ 87 µs plus one bridge tick), never "forever" and never a partial sequence.

### 1.4 Line discipline, measured (byte by byte)

| Case | Result |
| --- | --- |
| printables | buffered (5 chars for `1 2 +`), echoed by the ULP, **nothing interpreted** before the terminator (`sp == 0`) |
| `0x08` BS | erases one char, echoes `\b \b` exactly |
| `0x7F` DEL | identically |
| `0x0D` CR | line interpreted (`1 2 +` → 3), echoes `\n` then ` ok\n` |
| `0x0A` LF | identically (`7 1 -` → 6) |
| other control bytes | ignored, **counted** (2 seen for 2 sent), never echoed, surrounding line still interprets |
| 129-byte line | `ERR_LINE_TOO_LONG`, line dropped, `HERE` and `LATEST` byte-identical, nothing executed, the tail swallowed rather than interpreted, next line still runs |
| bonus: line split across two ring refills | `5 DU` + `P *\r` → 25, echoed exactly once |

### 1.5 Flow control

Water mark 96 B (75 % of 128): feeding 198 bytes of valid short lines at once, `br_feed()` consumed
exactly **96** and returned, `xoff = 1`, and the state line said `XOFF`. Re-offering the tail after
each ULP drain: **198 / 198 accepted, 198 / 198 pulled, `dropped == 0`, checksums equal** (order and
identity), Forth stack neutral, no line corrupted. Nothing is ever dropped silently — bytes the bridge
refuses stay in the caller's buffer and are counted in `refused`.

---

## 2. Evidence

### 2.1 Files (all new, all inside this directory)

| File | What it is |
| --- | --- |
| `uforth.c` | copy of `probe/uforth/uforth.c` with two additions: (i) `pl_hooks()` so the byte source/sink can be injected without the interpreter knowing about rings, (ii) `repl_step(k, nchars)` — P04's sliced seam with the line discipline of `06-repl.md` §4, including a **named** `ERR_LINE_TOO_LONG` instead of `forth_quit()`'s silent truncation. `forth_quit()`, `interpret()` and every primitive are untouched. |
| `bridge.h`, `bridge.c` | the bridge model, a separate object with **no dependency on the interpreter**: `cmd[128]`, `out[256]`, the `0x1D` state machine with exactly one byte of lookahead, the XOFF water mark, counters, the ASCII state line |
| `p10_test.c` | 51 checks: escape table, line discipline, XOFF round trip, double echo |
| `measure_esc.py` | the false-positive scan + the 2000-line synthetic corpus generator |
| `corpus_synth.fs` | the generated corpus (2000 lines, 63.6 KB) |
| `build.sh` | builds and runs the baseline suite, then the probe, each under `timeout` |
| `*.log` | `baseline-copy.log`, `baseline-uforth.log`, `p10-test.log`, `esc-scan.log`, `build.log` |

### 2.2 Commands (all under `timeout`; no `&`, no `/tmp`, no `head`-piped runs)

```
./build.sh
#   baseline: 58 passed, 0 failed
#   gcc -DHOST -std=c99 -Wall -Wextra -c bridge.c   (separate object: it links without uforth.c)
#   P10: 51 passed, 0 failed
python3 measure_esc.py          # 0x1D count 0, 0.000/10 KB, both corpora
```

The baseline was also run against the **unmodified** `probe/uforth/host_test.c` in this directory
(`baseline_test`, `baseline-copy.log`) and against `probe/uforth/` itself
(`baseline-uforth.log`): `58 passed, 0 failed` both times.

### 2.3 Where the model stops

The bridge is a byte-level model: rings, water mark, escape lookahead and the line discipline are
real; USB timing, the CH343 FIFO, `TIOCEXCL` and the dead-man window are not simulated (P11). The
"poll" that bounds the escape flush is the model's scheduling granularity, so the flush bound is
stated in polls, not microseconds.

---

## 3. Verdict

**Pass** on all four criteria, with one requirement that does *not* hold end-to-end and one design gap.

Pass criteria: every escape and line-discipline case behaves as `06-repl.md` §3–§4 states (6/6, 7/7);
XOFF loses nothing; no double echo; suite 58/58.

**Finding F1 — R8 item 4 (`0x1D` round-trips verbatim) is not satisfiable as written.** The escape
delivers the literal byte to the ULP input ring correctly, but §4's own line discipline discards every
`c < 0x20`, so `0x1D 0x1D` + `ABC` reaches the interpreter as `ABC`, and a lone literal `0x1D` never
survives into a line. Executed: after `ESC ESC` + `\r` the output is exactly `"\n ok\n"` — zero `0x1D`
bytes out. So the bridge half of the requirement holds and the round trip does not. Either the escape's
literal form must be admitted into the line buffer (a special case in §4), or R8 item 4 must be
restated as "the bridge delivers one literal `0x1D` to the ULP input ring" and the console has no way
to type a bare `0x1D`. The deltas below take the second route, because it keeps §4's
"control bytes are ignored" rule total.

**Finding F2 — at XOFF the state line is unreachable.** The bridge stops reading the port at the water
mark, and the `0x1D s` request arrives through that same port, so an operator cannot ask *why* input
stopped. The fix is two bytes of slack: check a pending escape (or an incoming `0x1D`) **before** the
water-mark test, so 126 B of the 128-byte ring still bound console input while control sequences keep
working. Executed consequence of not fixing it: with the ring at the water mark, feeding `ESC s` is refused
like any other byte (`br_feed` returns 0, nothing out), so the state line that would explain the stall
cannot be requested. The probe asserts this as today's behaviour on purpose.  

*this is a pre-fix behaviour record, not a pass criterion.*

**Finding F3 — the line limit and the ring size are two different numbers.** `cmd` is 128 B but the
prototype's line buffer is `TIBSZ = 80`, so `ERR_LINE_TOO_LONG` actually fires at **79 characters**,
not at 128, and the ring can hold a byte more than one line's worth. R8 item 8's 129-byte line is
satisfied a fortiori, but `06-repl.md` should state one number for both (see delta 3).

No failure criterion fired: the escape rate is 0, the unknown escape consumes nothing, XOFF loses no
byte, and there is no double echo.

---

## 4. Doc deltas (verbatim — `docs/` was not edited)

### Delta 1 — `docs/06-repl.md` §3, replace the whole section body under the heading

```markdown
One control character is reserved: **`0x1D`** (Ctrl-]), because it is the convention users already
know from telnet and tmux, and because Forth source never contains it: measured over every `.fs` file
in the repo (10 files, 22.6 KB) plus a 2000-line synthetic corpus in `boot_min.fs` style (63.6 KB),
`0x1D` occurs **0 times in 86.1 KB — 0.000 per KB, 0.00 per 10 KB** (P10). All source files are pure
printable ASCII, so the collision rate over source is structurally zero; the byte can only appear via
a binary paste.

| Sequence | Meaning |
| --- | --- |
| `0x1D 0x1D` | one literal `0x1D` delivered to the ULP input ring |
| `0x1D 'f'` | switch the bridge to framed mode |
| `0x1D 'p'` | back to passthrough |
| `0x1D 's'` | bridge state: mode, ring occupancy, drops, XOFF, accepted/refused (ASCII, one line) |
| `0x1D 'q'` | drop the ULP to autonomous mode and quit the session |

Rules that keep this safe:

* the bridge holds **one byte of lookahead, never more**. A `0x1D` at the end of a burst is flushed as
  a literal at the first poll whose source is empty — a bound of one bridge poll (≈ one byte time,
  87 µs at 115200, plus one tick), not of "the next character";
* an unknown sequence after `0x1D` is emitted verbatim (**both** bytes), so a bad escape cannot eat
  text (measured: `0x1D x` → ring holds `0x1D`, `'x'`);
* `0x1D f` / `0x1D p` / `0x1D q` put **zero** bytes into the ULP ring; `0x1D s` puts zero bytes into
  the ring and one line into the console stream;
* framed mode has its own framing (COBS + CRC-16 as in `02-harness.md`), so it cannot be confused
  with console text;
* `0x1D 0x1D` costs exactly one extra byte.

Two limits, measured in P10:

* the literal `0x1D` is delivered to the ULP input ring, **not** into a line: §4's line discipline
  ignores every byte below `0x20`, so a bare `0x1D` never survives into the interpreter. There is no
  way to type a literal Ctrl-] into Forth text, and no requirement depends on one;
* the escape is only usable while the bridge is reading the port, so the water-mark check of §5 must
  come **after** escape recognition, or `0x1D s` cannot be used to diagnose an XOFF.
```

### Delta 2 — `docs/06-repl.md` §4, replace the table and add the boundary note

```markdown
| Input | Behaviour |
| --- | --- |
| `0x20`–`0x7E` | buffered, echoed by the **ULP** (host local echo must be off); nothing is interpreted until the terminator |
| `0x08` / `0x7F` | erase one character; echo `\b \b` |
| `0x0D` or `0x0A` | end of line, echo `\n`, interpret |
| other control bytes | ignored, not echoed, **counted** in the state line |
| line longer than the input buffer | `ERR_LINE_TOO_LONG`, **line dropped**, dictionary byte-identical, and the rest of the line swallowed rather than interpreted — never truncated silently |
| ULP not running / stale heartbeat | bridge replies `ERR_NO_ULP` instead of accepting input into a void |

The line limit is the ULP input-buffer size, and it is **not** the command-ring size: `cmd` is 128 B
(P04) while `TIBSZ` is 80 B in the prototype, so the named error fires at **79 characters buffered**,
not at 128. The two numbers must be made equal (one line = one buffer) before R8 item 8 is written as
"a 129-byte line"; measured in P10, a 79-character line already yields `ERR_LINE_TOO_LONG`, with
`HERE` and `LATEST` unchanged and nothing executed.

Echo comes from the ULP, which means the echo you see is proof the characters actually arrived — a
useful property with no debugger available. P10 verified the host adds nothing: with host echo off the
bytes out equal the ULP's echo byte for byte (`5 DUP *\r` → `"5 DUP *\n ok\n"`), and no line appears
twice.
```

### Delta 3 — `docs/06-repl.md` §5, insert after the first two bullets

```markdown
* Measured in P10 (host model, `probe/results/P10-repl-host/`): at 96 B the bridge stops accepting,
  reports `xoff=1 XOFF` in its state line, and loses **nothing** — 198 bytes offered, 198 accepted,
  198 pulled, in order, no duplicates, `drops == 0`. Refused bytes stay in the caller's buffer and are
  counted in `refused`; the ring is never wrapped and never overwritten.
* **The water-mark test must come after escape recognition.** The bridge stops reading the port above
  75 %, and `0x1D s` arrives through that same port, so with the naive ordering an operator cannot ask
  why input stopped. Recognise a pending `0x1D` first: control sequences then cost at most 2 of the
  128 bytes and console input is still bounded at 96.
```

### Delta 4 — `docs/01-proposal.md` §10, R8 items 4, 5 and 8

```markdown
- [ ] A line containing `0x1D` round-trips verbatim, and `0x1D 0x1D` produces exactly one literal
      `0x1D`. *(P10: the bridge delivers exactly one literal `0x1D` to the ULP input ring, and an
      unknown sequence like `0x1D x` passes both bytes through untouched; the literal byte does not
      survive into the interpreter, because the line discipline ignores bytes below `0x20`. Restated
      as: `0x1D` costs one extra byte, consumes nothing on a miss, and never eats text. `0x1D` occurs
      0 times in 86.1 KB of real + synthetic source = 0.00 per 10 KB.)*
- [ ] A second opener on the port is refused with a named error and does not disturb the first
      session. *(not P10 — host model only; P11)*
- [ ] A 129-byte line yields `ERR_LINE_TOO_LONG`, the line is dropped, and the dictionary is
      byte-identical afterwards. *(P10: verified with `HERE` and `LATEST` unchanged and nothing
      executed; the boundary is the 80-byte prototype input buffer, so the error actually fires at 79
      characters — the number in this item and the buffer size must be reconciled.)*
```

---

## 5. Follow-ups

1. **Restate R8 item 4** (delta 4). This is a requirements change, not a code change: as written it
   contradicts §4's own control-byte rule. Someone must choose between "admit a `0x1D` into the line
   buffer" and "the escape stops at the ULP input ring".
2. **Escape recognition before the water mark** (delta 3, finding F2). Two lines of code in the real
   bridge, but it is a behaviour change, so it is not made here; it should be a release criterion for
   R8 item 7 (`monitor` interleaved with `forth` must work while input is flowing).
3. **One number for the line limit and the ring** (delta 2, finding F3): `TIBSZ` 80 vs `cmd` 128.
   Either raise `TIBSZ` to 128 (`+48 B` of RTC RAM) or lower the ring to 80; P10 measured the error
   but the choice is a memory-budget decision, not a probe result.
4. **P11 still owes**: the real poll period for the escape-flush bound, `TIOCEXCL` behaviour, the
   dead-man window, and whether the CH343 FIFO adds a second unmeasured buffer in front of `cmd`.
5. The probe's own `feed()` re-offer loop is the protocol `ulpctl` should use (offer, drain, re-offer
   the tail, never drop); P04 measured that an unpaced paste loses 86–96 %, which is the same missing
   loop.
