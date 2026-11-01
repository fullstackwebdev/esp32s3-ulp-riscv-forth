#!/usr/bin/env python3
"""frames.py — THE frame reader. One implementation, two callers.

`tests/tui_cli.py` grew this reader first (pty + `SENT` sentinel) and it encodes two measurements that are easy to lose:

  * a frame must have an END. Reading until a title appeared left the rows in the pipe and they landed in the NEXT read -
    measured as "0 red rows" for a frame that had one, immediately followed by "2 red rows" for a frame that had one.
  * a reader that stops at the first match cannot see a flood that starts after it. `dwell()` reads for the whole
    window on purpose: that is how the `ERR_ULPCODE` flood got past a green run.

GUARDRAIL: the App Store wave originally added a second terminal driver (`tools/screen.py` reading the stream itself)
beside this one. Two readers is how "works in one tool, not the other" starts, and the pty/select/lock handling is
exactly the part that must not fork. `screen.py` imports from here and adds only the ANSI -> cell-grid projection; do not
re-implement the read, the pty, or the board lock in a third place.

Nothing here interprets ANSI: this module returns BYTES. Interpretation belongs to `screen.py`, which is allowed to be
fatal on codes it does not know.
"""
import os
import select
import time

SENT = b"\x00"          # every drawn frame ends with this; `frame()` is the only place it is named


def read_until(fd, needle, cap):
    """Read from `fd` until `needle` is present or `cap` seconds pass. Returns the bytes read (never raises)."""
    buf, end = b"", time.time() + cap
    while time.time() < end and needle not in buf:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                buf += os.read(fd, 65536)
            except OSError:
                break
    return buf


def dwell(fd, cap):
    """Read for the WHOLE cap, ignoring quiet. A busy-looping program is silent until it is not, so a reader that stops
    at the first frame that matched a needle cannot see a flood that starts afterwards."""
    buf, end = b"", time.time() + cap
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                c = os.read(fd, 65536)
            except OSError:
                break
            if not c:
                break
            buf += c
    return buf


def frame(fd, cap=10.0):
    """Read exactly ONE drawn frame - every frame ends with the SENT sentinel (0x00).

    GUARDRAIL: reading until the TITLE desynchronises the stream. "PROGRAM LIBRARY" appears before the rows, so the rows
    stay in the pipe and land in the NEXT read - measured as "0 red rows" in a frame that had one, immediately followed
    by "2 red rows" in a frame that had one. A reader that cannot say where a frame ends cannot count anything inside it.
    """
    return read_until(fd, SENT, cap)


def drain(fd, cap=0.3):
    """Throw away whatever is pending (a program that draws while nobody is listening leaves a frame in the pipe)."""
    return dwell(fd, cap)
