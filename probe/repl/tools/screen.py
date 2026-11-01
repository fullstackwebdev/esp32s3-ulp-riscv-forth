#!/usr/bin/env python3
"""screen.py — drive one program and turn what it draws into a 24x80 character grid.

    # host: the same dictionary the chip runs, at device geometry (tests/build_host_app.sh makes it)
    tools/screen.py ../../examples/tui_min.fs --host artifacts/host_app --entry RUN --keys j --grid
    # device: /dev/ttyACM1, under the board lock
    tools/screen.py <phase.fs> --device --keys jj --grid
    # a golden, exactly as docs/26 files it: 24 lines of 80 cells
    tools/screen.py <phase.fs> --host artifacts/host_app --keys j --expect tests/apps/<app>.host.txt

WHY: docs/26 gives every screen one geometry (80x24, title row 1, footer row 24) and one key vocabulary, and G2/G4
are "the host golden" and "host == device". Both of those need something that turns a byte stream into CELLS, because
`grep ULP FORTH` in a 900-byte frame proves nothing about row 13 (R12: a green check certifies only what it reads).

GUARDRAIL: the HOST backend must load the SAME dictionary the chip runs, not a re-derived one. On the chip the
dictionary is src/image.h (baked by tools/bake.sh, 2 476 of 2 604 bytes); re-loading src/p39_prelude.fs on the host
instead would compile a different dictionary - the prelude's lines are up to 104 characters and the device TIB is 96,
so the host would have to load them in a way the chip never does. tests/build_host_app.sh therefore builds host_app
with -DIMAGE, and this file only ever feeds it PROGRAM text.

GUARDRAIL: the host's KEY is `getchar()` and its KEY? is a constant 1 (uforth.c pl_key/pl_keyq, HOST build), while the
chip's KEY returns -1 when nothing is waiting. So a phase must block in KEY (`BEGIN KEY DUP -1 = WHILE DROP REPEAT`,
examples/tui_min.fs K0) and must never poll KEY? - a KEY? loop spins forever on the host (pl_keyq()==1 with EOF behind
it) and sees "no key" for the first 6.5 ms on the chip. The two backends agree on WHICH KEYS the program sees, in
order, and on nothing about idle time. That is enough for a grid; it is not enough for a spinner test.

GUARDRAIL: pl_key() on the host EXITS the process on EOF. So the last key bytes in --keys are followed by "end of
input", i.e. the program draws one more frame and then leaves at its next KEY. Pass the program's own exit key as the
last key (usually `q`) so both backends leave through the same arm.

GUARDRAIL: the grid is CELLS ONLY - characters, no attributes. Inverse is consumed (ESC[7m/ESC[0m) but not recorded,
because docs/26 files a golden as "24x80 cells, exactly as drawn" and a colour must be asserted on the raw bytes (as
tests/tui_menu.py counts `ESC[31m`), not invented into a text file.

GUARDRAIL: an escape sequence this file does not understand is FATAL, not skipped. The machine's whole vocabulary is
ALT/NORM/HIDE/SHOW/CLR/HOME/AT/INV/OFF/COL (examples/menu.fs) plus the cursor moves below; a new one means the grid is a
guess, and a guessed grid that still matches a golden is the worst outcome available. Unknown code -> exit 3, named.

Exit codes: 0 ok; 1 golden mismatch; 2 harness/program failure (named reason); 3 the stream carried a code this file
cannot interpret; 4 no board (device only).
"""
import argparse
import contextlib
import fcntl
import os
import pathlib
import select
import subprocess
import sys
import tempfile
import time

TOOLS = pathlib.Path(__file__).resolve().parent
PROBE = TOOLS.parent                      # probe/repl
REPO = PROBE.parent.parent                # the checkout root
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

HOST_APP = PROBE / "artifacts" / "host_app"
EXPAND = PROBE / "artifacts" / "expand"
# GUARDRAIL: the lock is the one device.sh takes (`probe/results/.board.lock`, flock(2)); fcntl.flock here is the same
# lock domain, so a screen run and a device.sh run exclude each other. Two processes on one UART produced "fresh boot"
# failures that were really two readers, and a reset in the middle of another run's frame.
LOCK = REPO / "probe" / "results" / ".board.lock"
PORT = "/dev/ttyACM1"
ROWS, COLS = 24, 80

ESC = 0x1b


class HarnessError(RuntimeError):
    """Anything that stops the run for a reason we can name: missing binary, refused program, malformed golden."""


class NoBoard(HarnessError):
    """No board answered on the port. A different fact from 'the program is wrong', so it gets its own exit code."""


class Uninterpreted(HarnessError):
    """The stream carried a code this file cannot interpret, so the grid would be a guess. Its own exit code, because
    the fix is to teach screen.py the code - not to change the program."""


# ---------------------------------------------------------------- the grid -------------------------------------------------
class Grid:
    """24 rows x 80 columns of characters. Row 0 is the terminal's row 1."""

    def __init__(self):
        self.cells = [[" "] * COLS for _ in range(ROWS)]

    def clear(self):
        self.cells = [[" "] * COLS for _ in range(ROWS)]

    def text(self):
        return "\n".join("".join(row) for row in self.cells)

    def lines(self):
        return ["".join(row) for row in self.cells]


class Terminal:
    """Interpret the machine's own ANSI codes into a Grid.

    The vocabulary is read off examples/menu.fs (the words the programs actually use) plus the cursor moves a terminal
    must honour; there is no third-party parser and no interpretation of anything the machine cannot emit.
    """

    def __init__(self):
        self.grid = Grid()
        self.row = self.col = 0
        self.warnings = []          # deterministic-but-suspect: off-screen writes, scrolls, overlong lines

    # ---- output -----------------------------------------------------------------------------------------------
    def feed(self, data):
        i, n = 0, len(data)
        while i < n:
            b = data[i]
            if b == ESC:
                if i + 1 >= n:
                    raise Uninterpreted(f"truncated escape at the end of the stream: {data[i:]!r}")
                if data[i + 1] != 0x5b:                     # not CSI: ESC 7/8, ESC ( B, ...
                    raise Uninterpreted(f"uninterpreted escape {data[i:i + 2]!r} - teach screen.py this code")
                j = i + 2
                while j < n and not (0x40 <= data[j] <= 0x7e):
                    j += 1
                if j >= n:
                    raise Uninterpreted(f"truncated CSI at the end of the stream: {data[i:]!r}")
                self.csi(data[i + 2:j], data[j])
                i = j + 1
            elif b == 0x00:
                # GUARDRAIL: the programs end every frame with SENT (examples/menu.fs `: SENT 0 EMIT`), a byte a
                # terminal ignores. Consume it, never draw it: a NUL printed into the grid is invisible in a diff and
                # would then differ between backends for no reason.
                i += 1
            elif b == 10:
                self.line_feed()
                i += 1
            elif b == 13:
                self.col = 0
                i += 1
            elif b == 8:
                self.col = max(0, self.col - 1)             # MSG_ERASE is "\b \b": back, space, back
                i += 1
            elif 32 <= b < 127:
                self.put(chr(b))
                i += 1
            else:
                # GUARDRAIL: a byte >= 0x80 here means the stream was NOT expanded (src/msg_codes.h starts at 0x81) -
                # the host path pipes through tools/expand.c for exactly this reason. Drawing it would hide a missing
                # filter; naming it costs one line.
                raise Uninterpreted(f"byte 0x{b:02x} in the stream is not ASCII: the stream still carries message "
                                   f"codes (src/msg_codes.h) - expand it before it reaches this function")

    def put(self, ch):
        if self.row >= ROWS or self.col >= COLS:
            self.warnings.append(f"write past the screen at row {self.row + 1} col {self.col + 1} ({ch!r})")
        else:
            self.grid.cells[self.row][self.col] = ch
        self.col += 1

    def line_feed(self):
        self.col = 0
        self.row += 1
        if self.row >= ROWS:
            # GUARDRAIL: scroll like the terminal does (rows shift up) instead of clamping, because clamping silently
            # merges two frames' worth of writes into the last row. It is still reported: a screen that scrolls has
            # printed more than 24 lines and the golden would be recording the accident.
            self.grid.cells.pop(0)
            self.grid.cells.append([" "] * COLS)
            self.row = ROWS - 1
            self.warnings.append("the screen scrolled: more than 24 lines were printed")

    def at(self, row, col):
        """ESC[<row>;<col>H - 1-based, defaults 1;1, clamped to the grid."""
        if not (1 <= row <= ROWS and 1 <= col <= COLS):
            self.warnings.append(f"cursor moved off the screen: row {row} col {col}")
        self.row = min(max(row, 1), ROWS) - 1
        self.col = min(max(col, 1), COLS) - 1

    def csi(self, params, final):
        text = params.decode("latin-1")
        private = text.startswith("?")
        body = text.lstrip("?")
        nums = [int(p) if p.isdigit() else 0 for p in body.split(";")] if body else []
        f = chr(final)
        if f in "Hf":                                        # AT
            self.at(nums[0] if nums and nums[0] else 1, nums[1] if len(nums) > 1 and nums[1] else 1)
        elif f == "J":                                       # CLR
            mode = nums[0] if nums else 0
            if mode == 0:
                self._erase(self.row, self.col, ROWS - 1, COLS - 1)
            elif mode == 1:
                self._erase(0, 0, self.row, self.col)
            elif mode in (2, 3):
                self.grid.clear()                            # cursor does NOT move: menu.fs does CLR then HOME
            else:
                raise Uninterpreted(f"uninterpreted erase ESC[{text}J - teach screen.py this code")
        elif f == "K":                                       # erase in line
            mode = nums[0] if nums else 0
            if mode == 0:
                self._erase(self.row, self.col, self.row, COLS - 1)
            elif mode == 1:
                self._erase(self.row, 0, self.row, self.col)
            elif mode == 2:
                self._erase(self.row, 0, self.row, COLS - 1)
            else:
                raise Uninterpreted(f"uninterpreted erase ESC[{text}K - teach screen.py this code")
        elif f == "m":
            # SGR: OFF (0), INV (7), COL n (ESC[3n m), bold/39/49. The grid is characters only; the codes are consumed
            # so they cannot be mistaken for text.
            pass
        elif f in "ABCD":
            step = nums[0] if nums and nums[0] else 1
            if f == "A":
                self.row = max(0, self.row - step)
            elif f == "B":
                self.row = min(ROWS - 1, self.row + step)
            elif f == "C":
                self.col = min(COLS - 1, self.col + step)
            else:
                self.col = max(0, self.col - step)
        elif f in "hl" and private and nums and nums[0] == 1049:
            # ALT/NORM (the alternate screen). Entering gives a clean screen, exactly as the terminal does; leaving
            # restores the operator's, which we do not model - the frame we want is the one the program drew.
            if f == "h":
                self.grid.clear()
                self.row = self.col = 0
        elif f in "hl" and private:
            pass                                             # ?25h/?25l (cursor show/hide) and friends: no cells
        else:
            raise Uninterpreted(f"uninterpreted CSI ESC[{text}{f} - teach screen.py this code")

    def _erase(self, r0, c0, r1, c1):
        for r in range(max(0, r0), min(ROWS - 1, r1) + 1):
            for c in range(max(0, c0), min(COLS - 1, c1) + 1):
                self.grid.cells[r][c] = " "


# ---------------------------------------------------------------- goldens --------------------------------------------------
def parse_golden(text, name):
    """A golden is EXACTLY 24 lines of 80 cells. Anything else is a harness defect, not a near miss."""
    lines = text.splitlines()
    if len(lines) != ROWS:
        raise HarnessError(f"{name}: {len(lines)} rows, expected {ROWS} - a golden is the whole screen")
    for i, ln in enumerate(lines):
        if len(ln) != COLS:
            raise HarnessError(f"{name}: row {i + 1} has {len(ln)} characters, expected {COLS} "
                               f"(trailing spaces are part of the cell)")
    return lines


def diff_grid(want, got):
    """Every differing cell, in reading order. Callers decide what to print."""
    out = []
    for r in range(ROWS):
        for c in range(COLS):
            if want[r][c] != got[r][c]:
                out.append((r, c, want[r][c], got[r][c]))
    return out


def describe_cell(r, c, want, got):
    return f"row {r + 1:2d} col {c + 1:2d}  expected {want!r} (0x{ord(want):02x})  got {got!r} (0x{ord(got):02x})"


# ---------------------------------------------------------------- HOST backend --------------------------------------------
def check_blocks(program, first_block):
    """Refuse on the host what the board would refuse: the same splitter cli.py uses, one owner (R6).

    GUARDRAIL: without this the host happily compiles a definition that does not fit one 128 B block and the failure
    appears only as G4 - on the chip - where it costs a session. fsplit refuses it here, by name, for free.
    """
    from fsplit import split_defs
    src = program.read_text()
    try:
        blocks = split_defs(src, 92)
    except SystemExit as e:                                  # fsplit's own refusal, verbatim
        raise HarnessError(str(e))
    if first_block + len(blocks) > 128:
        raise HarnessError(f"{program.name} is {len(blocks)} block(s) from block {first_block}, which passes block 127; "
                           f"the block server refuses anything above 127 with BK_RANGE")


def run_host(program, entry, keys, binary=HOST_APP, timeout=60.0):
    """Build the byte stream the way the chip produces it: run the engine, capture stdout, expand the message codes."""
    binary = pathlib.Path(binary)
    if not binary.exists():
        raise HarnessError(f"no host binary at {binary} - build it with tests/build_host_app.sh")
    if not EXPAND.exists():
        raise HarnessError(f"no {EXPAND} - build it with tests/build_host_app.sh")
    # GUARDRAIL: the entry word goes in its own file, loaded AFTER the program, because host_app's argv order IS the
    # compile order (`load()` per file). Appending the word to a copy of the program would run a source that is not
    # byte-identical to the one the board seeds.
    with tempfile.TemporaryDirectory(prefix="screen.") as tmp:
        driver = pathlib.Path(tmp) / "entry.fs"
        driver.write_text(entry + "\n")
        cmd = [str(binary), str(program), str(driver)]
        try:
            out = subprocess.run(cmd, input=keys, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise HarnessError(
                f"{program.name} did not return within {timeout:.0f}s on the host - a phase must block in KEY "
                f"(the host's KEY? is a constant 1, so a KEY? loop hangs here; see this file's header)")
    err = out.stderr.decode("latin-1")
    for bad in (": error", "stack underflow", "line too long", "cannot open"):
        if bad in err:
            raise HarnessError(f"the host engine refused {program.name}: {err.strip()}")
    if out.returncode != 0:
        raise HarnessError(f"host_app exited {out.returncode}: {err.strip()[:400]}")
    raw = subprocess.run([str(EXPAND)], input=out.stdout, capture_output=True, timeout=30.0)
    return raw.stdout


# ---------------------------------------------------------------- DEVICE backend ------------------------------------------
def board_lock():
    """The board lock device.sh takes, in-process. Same file, same flock(2) lock domain."""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o664)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise HarnessError(f"board busy: another device run holds {LOCK.relative_to(REPO)} "
                           f"(two processes on one UART is how a 'fresh boot' failure is faked)")
    return fd


def key_units(data):
    """One keystroke per unit. ESC [ X is THREE bytes and must be written in one go: the HP queues up to 8 raw bytes
    per wake and feeds the ULP's one-cell keybox, so a sequence split across two writes is delivered intact only by
    luck (docs/25: the keybox delivers sequences intact)."""
    units, i = [], 0
    while i < len(data):
        if data[i] == ESC and i + 2 < len(data) and data[i + 1] == 0x5b:
            units.append(data[i:i + 3])
            i += 3
        else:
            units.append(data[i:i + 1])
            i += 1
    return units


def decode_keys(text):
    """`--keys` escapes, because an arrow key is ESC [ B and a shell argument cannot hold a raw ESC comfortably."""
    out = bytearray()
    i = 0
    table = {"e": 0x1b, "r": 0x0d, "n": 0x0a, "t": 0x09, "\\": 0x5c, "0": 0x00}
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == "x" and i + 3 < len(text):
                out.append(int(text[i + 2:i + 4], 16))
                i += 4
                continue
            if nxt in table:
                out.append(table[nxt])
                i += 2
                continue
            raise HarnessError(f"--keys: unknown escape \\{nxt} (known: \\e \\x1b \\r \\n \\t \\0 \\\\)")
        out.extend(ch.encode())
        i += 1
    return bytes(out)


def read_bytes(dev, quiet=0.30, cap=8.0):
    """Read until the line has been quiet for `quiet` seconds, or `cap` runs out.

    GUARDRAIL: devio.drain() is not usable here - it decodes with errors='replace', so a frame is inspected as text that
    already lost the bytes we are judging. This returns the raw bytes the board sent.
    GUARDRAIL: a frame ends with SENT (0x00), so in principle the sentinel could stop the read. It is not used as the
    stop condition: a frame that is missing its sentinel (a program that died mid-frame) would then read until the cap
    and look identical to a slow one. Quiet + cap is honest about both.
    """
    buf = b""
    end = last = time.time()
    end += cap
    while time.time() < end:
        r, _, _ = select.select([dev.fd], [], [], 0.02)
        if r:
            c = os.read(dev.fd, 8192)
            if c:
                buf += c
                last = time.time()
        elif time.time() - last > quiet:
            break
    return buf


# GUARDRAIL: MSG_OK is ` ok\n` (src/msg_codes.h) and the console prints it when the LINE that started the program
# finishes - i.e. at the moment the program returns. It is the console's completion marker, not the program's drawing,
# and it lands at the cursor right after the last frame: left in, it writes " ok" into row 24 of the grid and every
# golden recorded from a run whose last key was `q` (the normal case!) is wrong by three cells. It is also the exact
# signal that the program has returned, which is what stops leave_device() writing a `q` nobody will read.
PROGRAM_RETURNED = b" ok\n"


def leave_device(dev, returned=False):
    """Give the machine back, and never raise from a cleanup step.

    GUARDRAIL: `q` REPEATEDLY, stopping at the first ` ok`: a program can be nested (the launcher runs an app), and one
    `q` leaves the app with the launcher still waiting - measured in cli.py as "no ok" with a single key. Stopping at the
    first ` ok` also avoids leaving a stale key that would quit the NEXT program on its first poll.
    GUARDRAIL: and when the program has ALREADY returned (the last --keys byte was its exit key) no `q` is sent at all:
    raw mode is still on, so it would be delivered into the ULP's single keybox cell and sit there until the next
    program's first KEY returns it - the measured "the next run quits instantly" trap, written down in cli.term().
    GUARDRAIL: `!LINE` has NO reply by design, so it is written without waiting and the machine is proved alive with a
    command that does answer (cli.term's own lesson - a wait there raised a traceback after a successful run).
    """
    try:
        if not returned:
            buf = b""
            for _ in range(3):
                os.write(dev.fd, b"q")
                buf += read_bytes(dev, quiet=0.25)
                if PROGRAM_RETURNED in buf:
                    break
            if PROGRAM_RETURNED not in buf:
                print("  WARNING: the program did not leave on q - the board may need a reset", file=sys.stderr)
        os.write(dev.fd, b"!LINE\r")
        dev.num("HERE .", timeout=4.0)
    except Exception as e:                                   # noqa: BLE001 - cleanup must not mask the real error
        print(f"  WARNING: could not confirm the machine is back at the prompt ({type(e).__name__}: {e})",
              file=sys.stderr)


def run_device(program, entry, keys, first_block=64, port=PORT):
    """Drive the program on the board, under the board lock, and return the raw byte stream of its DRAWING."""
    sys.path.insert(0, str(REPO))
    import cli                                              # noqa: E402 - cli.py inserts probe/tools on import

    returned = [False]                                      # set by draw(); read by the finally below

    def draw(buf):
        """Cut the console's ` ok\n` off the drawing, wherever it arrived."""
        if PROGRAM_RETURNED in buf:
            returned[0] = True
            return buf.split(PROGRAM_RETURNED, 1)[0]
        return buf

    fd = board_lock()
    try:
        # GUARDRAIL: cli.connect()/cli.upload() report progress on stdout, and stdout belongs to the grid. Everything the
        # harness says goes to stderr so `screen.py --grid > golden` cannot be polluted by a compile line.
        with contextlib.redirect_stdout(sys.stderr):
            dev = cli.connect(port, 0.25)
        if dev is None:
            raise NoBoard(f"no board on {port}: cli.connect printed the reason above (cable, port, or a stale holder)")
        try:
            with contextlib.redirect_stdout(sys.stderr):
                _n, bad = cli.upload(dev, str(program), first_block)
            if bad:
                raise HarnessError(f"{program.name} did not compile on the board: {bad}")
            dev.drain(0.05, 1.0)
            os.write(dev.fd, entry.encode() + b"\r")
            head = read_bytes(dev)
            want = entry.encode()
            # GUARDRAIL: the console ECHOES the typed line before the program's first byte, so the first frame is not at
            # the head of the read. The echo is exactly `entry + "\n"` (drain_cmd emits each printable byte, then a
            # newline on the CR), and it is cut here rather than by "skip until the first ESC": a program whose first
            # byte is text would lose that text.
            if not head.startswith(want):
                raise HarnessError(f"expected the echo of {entry!r} at the head of the first frame, got {head[:40]!r}")
            nl = head.find(b"\n", len(want))
            if nl < 0:
                raise HarnessError(f"no newline after the echo of {entry!r}: the entry word never ran "
                                   f"(got {head[:80]!r})")
            frame = draw(head[nl + 1:])
            # GUARDRAIL: !RAW goes out with the first frame ALREADY DRAWN, so the program is known to be sitting in KEY.
            # Sent before it starts (or on a fixed timer), the start word's own bytes are forwarded as keystrokes - the
            # reason cli.term() has the same comment in the opposite direction.
            os.write(dev.fd, b"!RAW\r")
            time.sleep(0.15)                                # the HP swallows CRs for 50 ms after !RAW
            for unit in key_units(keys):
                if returned[0]:
                    break                                   # the program is gone: a key now is a REPL command
                # GUARDRAIL: ONE key per write and a read after each. The HP queues raw bytes into an 8-byte ring and
                # feeds the ULP's ONE-cell keybox, so a paste can outrun it and drop the middle of an ESC [ B (the
                # reason the keybox is one cell and the host holds the queue). It also ends the run at the frame that
                # belongs to the last key, which is the frame the host produces at EOF.
                os.write(dev.fd, unit)
                frame += draw(read_bytes(dev))
                if returned[0]:
                    break
            return frame
        finally:
            with contextlib.redirect_stdout(sys.stderr):
                leave_device(dev, returned=returned[0])
            dev.close()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ---------------------------------------------------------------- CLI ------------------------------------------------------
def main(argv):
    ap = argparse.ArgumentParser(description="drive one program and turn its output into a 24x80 grid")
    ap.add_argument("program", metavar="PROGRAM", help="the .fs source (a phase defines one word and does not run it)")
    ap.add_argument("--host", metavar="BIN", default=None, help="run on the host engine at device geometry")
    ap.add_argument("--device", action="store_true", help=f"run on the board ({PORT}, under the board lock)")
    ap.add_argument("--entry", metavar="WORD", default=None,
                    help="the word to run after loading (default: the file's name uppercased, docs/26)")
    ap.add_argument("--keys", metavar="STR", default="",
                    help=r"keys to type, in order; \e is ESC (\e[B = Down), \r = Enter")
    ap.add_argument("--block", type=int, default=64, metavar="N", help="first block of the program (device), default 64")
    ap.add_argument("--port", default=os.environ.get("PORT", PORT))
    ap.add_argument("--timeout", type=float, default=60.0, help="host run cap in seconds (default 60)")
    ap.add_argument("--grid", action="store_true", help="print the 24x80 grid on stdout")
    ap.add_argument("--expect", metavar="FILE", default=None, help="diff against a 24x80 golden; exit 1 on any cell")
    a = ap.parse_args(argv)

    if bool(a.host) == bool(a.device):
        ap.error("say which backend: --host BIN or --device")
    if not (a.grid or a.expect):
        ap.error("nothing to do with the grid: pass --grid and/or --expect FILE")

    program = pathlib.Path(a.program)
    if not program.exists():
        raise HarnessError(f"no such program: {program}")
    entry = a.entry or program.stem.upper()
    keys = decode_keys(a.keys)
    check_blocks(program, a.block)

    if a.host:
        stream = run_host(program, entry, keys, binary=a.host, timeout=a.timeout)
    else:
        stream = run_device(program, entry, keys, first_block=a.block, port=a.port)
    term = Terminal()
    term.feed(stream)
    for w in dict.fromkeys(term.warnings):                  # dedupe, keep order: a repeated warning is noise
        print(f"  WARNING: {w}", file=sys.stderr)

    if a.grid:
        print(term.grid.text())
    if a.expect:
        want = parse_golden(pathlib.Path(a.expect).read_text(), a.expect)
        got = term.grid.lines()
        bad = diff_grid(want, got)
        if bad:
            for r, c, wch, gch in bad:
                print(describe_cell(r, c, wch, gch))
            first_row = bad[0][0]
            print(f"  MISMATCH: {len(bad)} of {ROWS * COLS} cells differ; first at row {first_row + 1} col {bad[0][1] + 1}")
            print(f"  want |{want[first_row]}|")
            print(f"  got  |{got[first_row]}|")
            return 1
        print(f"  {COLS}x{ROWS} grid matches {a.expect} ({ROWS * COLS} cells)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except NoBoard as e:
        print(f"screen: NO BOARD: {e}", file=sys.stderr)
        sys.exit(4)
    except Uninterpreted as e:
        print(f"screen: {e}", file=sys.stderr)
        sys.exit(3)
    except HarnessError as e:
        print(f"screen: {e}", file=sys.stderr)
        sys.exit(2)
