#!/usr/bin/env python3
"""tui_menu.py - end-to-end test of the full-screen Forth menu, every keystroke.

Reproducible: resets the board, uploads examples/tui_min.fs over the TTY, starts it, presses each key once and
checks what the chip drew. No mocks, no host-side menu: the program under test runs on the coprocessor.

    python3 tests/tui_menu.py            run the checks (exit 1 on any failure)
    python3 tests/tui_menu.py --capture  also save every raw frame under .auto/tmp/tui_frames/

GUARDRAIL: a single `>` in the frame is not enough to prove the selection MOVED - a redraw always has exactly one
marker. The signal is the CURSOR ADDRESS that precedes it (`ESC[<row>;<col>H`), so each check asserts the row.
GUARDRAIL: every frame is also scanned for `ERR_` and `?`. A sticky stack overflow kills the program silently: measured,
the first arrow key redrew 213 B and every key after it did nothing at all.
"""
import os
import pathlib
import re
import select
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
from devio import Dev                      # noqa: E402
from fsplit import split_defs              # noqa: E402

APP = HERE.parent.parent.parent / "examples" / "tui_min.fs"
FIRST = 100
FRAMES = HERE.parent / ".auto" / "tmp" / "tui_frames"
ROW_OF = {0: 4, 1: 5, 2: 6}                # menu item -> screen row in the app's layout
QUIET, CAP = 0.55, 3.0


def read_quiet(dev, quiet=QUIET, cap=CAP):
    """Collect everything the chip emits until it has been silent for `quiet` seconds.

    GUARDRAIL: raw mode has no prompt and no `ok`, so there is no marker to read until - silence is the only
    end-of-frame signal. A cap keeps a runaway program from hanging the test.
    """
    buf, end, last = b"", time.time() + cap, time.time()
    while time.time() < end:
        r, _, _ = select.select([dev.fd], [], [], 0.05)
        if r:
            buf += os.read(dev.fd, 8192)
            last = time.time()
        elif time.time() - last > quiet:
            break
    return buf


def marker_row(frame):
    """Row of the selection marker: the cursor move immediately before the single `>`."""
    # GUARDRAIL: allow SGR sequences between the cursor move and the marker. The app writes `AT` then `COL`, so the
    # frame reads ESC[row;colH ESC[3m ">" - a pattern that rejected escapes reported row=None while the marker was
    # plainly there (measured on the first frame of a working draw).
    hits = [m for m in re.finditer(rb"\x1b\[(\d+);\d+H(?:\x1b\[[0-9;]*m)*[ ]*>", frame)]
    return int(hits[-1].group(1)) if hits else None


def clean(frame):
    return b"ERR_" not in frame and b"stack?" not in frame


def key(dev, seq, label, expect_row, results, capture, idx):
    os.write(dev.fd, seq)
    frame = read_quiet(dev)
    if capture:
        FRAMES.mkdir(parents=True, exist_ok=True)
        (FRAMES / f"{idx:02d}_{label}.bin").write_bytes(frame)
    row = marker_row(frame)
    ok = (row == expect_row) and clean(frame) and len(frame) > 40
    results.append((label, ok, f"row={row} want={expect_row} bytes={len(frame)}" +
                    ("" if clean(frame) else "  ERROR IN FRAME")))
    return frame


def main(argv):
    capture = "--capture" in argv
    blocks = split_defs(APP.read_text(), 92)
    results = []
    dev = Dev()
    try:
        # GUARDRAIL: a reset that did not actually happen must not pass as one. Measured: an RTS pulse silently did
        # nothing, the still-running ULP answered politely, and the test compiled a second copy of the app into a full
        # dictionary - every block then failed with ERR_DICT and it looked like the app was too big. Assert a FRESH
        # machine: the baked dictionary always starts with HERE at 786 and ~1 300 B of app space.
        fresh = False
        for attempt in range(4):
            # fast path first (RTS pulse, ~50 ms), then the reliable but slow esptool reset: measured, the pulse
            # sometimes does nothing at all, and a "reset" that did not happen silently poisons the whole run.
            if attempt < 2:
                dev.pulse_reset(1.0)
            else:
                dev.reset(settle=1.2)
            try:
                # GUARDRAIL: use dev.num(). `cmd` returns the ECHO first, so splitting the reply gave the word "HERE"
                # and int() raised - the test then reported here=None for a board that was answering perfectly.
                here = dev.num("HERE .", timeout=5.0)
                free = dev.num("LATEST HERE - .", timeout=5.0)
            except Exception:
                continue
            if here < 900 and free > 900:
                fresh = True
                break
        results.append(("fresh boot (HERE ~786, app space ~1.3 KB)", fresh, f"here={locals().get('here')} free={locals().get('free')}"))
        if not fresh:
            report(results); return 1
        dev.cmd("0 2 BLKXFER", timeout=6.0, allow_error=True)
        missing = dev.seed_many([(FIRST + i, b) for i, b in enumerate(blocks)])
        if missing:
            print(f"  FAIL upload: blocks {missing} not acknowledged"); return 1
        bad = {}
        for i in range(len(blocks)):
            rep = dev.cmd(f"{FIRST + i} LOAD", timeout=25.0, allow_error=True)
            errs = [l.strip() for l in rep.splitlines() if l.strip().endswith("?") or "ERR_" in l]
            if errs:
                bad[FIRST + i] = errs[0]
        results.append(("compile", not bad, f"{len(blocks)} blocks" + (f" errors={bad}" if bad else "")))
        if bad:
            report(results); return 1

        os.write(dev.fd, b"RUN\r"); time.sleep(0.35)
        os.write(dev.fd, b"!RAW\r"); time.sleep(0.25)
        first = read_quiet(dev)
        if capture:
            FRAMES.mkdir(parents=True, exist_ok=True)
            (FRAMES / "00_first_frame.bin").write_bytes(first)
        ok = (b"\x1b[?1049h" in first and b"ULP FORTH" in first
              and marker_row(first) == ROW_OF[0] and first.count(b">") == 1 and clean(first))
        results.append(("first frame", ok,
                        f"alt={b'1049h' in first} title={b'ULP FORTH' in first} "
                        f"row={marker_row(first)} markers={first.count(b'>')}" +
                        ("" if clean(first) else f" tail={first[-30:]!r}")))

        key(dev, b"j", "j-down", ROW_OF[1], results, capture, 1)
        key(dev, b"j", "j-down-again", ROW_OF[2], results, capture, 2)
        key(dev, b"k", "k-up", ROW_OF[1], results, capture, 3)
        key(dev, b"\x1b[B", "arrow-down", ROW_OF[2], results, capture, 4)
        key(dev, b"\x1b[A", "arrow-up", ROW_OF[1], results, capture, 5)
        key(dev, b"\r", "enter", ROW_OF[1], results, capture, 6)      # Enter: redraw, no move
        key(dev, b"x", "unknown-key", ROW_OF[1], results, capture, 7)  # ignored, marker must stay

        os.write(dev.fd, b"q")
        tail = read_quiet(dev)
        if capture:
            (FRAMES / "08_quit.bin").write_bytes(tail)
        left = b"\x1b[?1049l" in tail
        results.append(("q leaves the alternate screen", left, f"{len(tail)} B, restore={left}"))
        dev.cmd("!LINE", timeout=8.0, allow_error=True)
        alive = dev.cmd("2 3 + .", timeout=8.0, allow_error=True)
        results.append(("REPL usable afterwards", "5" in alive, alive.strip()[:24]))
        return report(results)
    finally:
        dev.close()


def report(results):
    print()
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:30s} {detail}")
    bad = [n for n, ok, _ in results if not ok]
    print(f"  {len(results) - len(bad)}/{len(results)} checks pass" + (f"  FAILED {bad}" if bad else ""))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
