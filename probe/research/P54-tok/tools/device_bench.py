#!/usr/bin/env python3
"""P52 device bench driver — send Forth lines to the on-chip REPL, collect per-line rdcycle counts.

The ULP prints, after every interpreted line, a marker on its own line:

    C <cycles> D <dispatches>

`cycles` is `rdcycle` across `run_line()`, `dispatches` is the engine's own counter. Both are read at the
LINE BOUNDARY, never inside the dispatch loop (see the GUARDRAIL in ulp_repl.c), so the instrument does not
perturb what it measures.

GUARDRAIL: lockstep, one line in flight. The ULP's output ring is 128 B and its command ring is 64 B; a
driver that pastes a whole file overruns one of them and then attributes a marker to the wrong line — a
wrong number that looks exactly like a right one. Send, wait for the marker, then send.
GUARDRAIL: comments (`\\`) and blank lines are dropped before sending, not after. They still consume TIBSZ
when typed, and a line over the buffer produces MSG_LINE_TOO_LONG, which CLEARS the line — so the workload
silently loses a definition and every number after it is for a different program.
GUARDRAIL: never /dev/ttyACM0. That is the USB-serial-JTAG port this board enumerates as well, and writing
Forth to it reaches nothing (or a different console).
"""
import os
import re
import select
import sys
import termios
import time

DEV = "/dev/ttyACM1"
BAUD = termios.B115200
MARK = re.compile(rb"C (\d+)\s*D (\d+)")
TIBSZ = 128


def open_port():
    fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY)
    a = termios.tcgetattr(fd)
    a[0] = 0                                   # iflag
    a[1] = 0                                   # oflag
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    a[3] = 0                                   # lflag: no echo, no line discipline
    a[4] = a[5] = BAUD
    a[6][termios.VMIN] = 0
    a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd


def drain(fd, quiet=0.25, limit=5.0):
    """Read until the line goes quiet, so a stale marker cannot be matched to the next line."""
    buf = b""
    end = time.time() + limit
    last = time.time()
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            chunk = os.read(fd, 4096)
            if chunk:
                buf += chunk
                last = time.time()
        elif time.time() - last > quiet:
            break
    return buf


def send_line(fd, line, timeout=25.0):
    """Send one line, return (cycles, dispatches, echo); cycles is None if the marker had no numbers.

    GUARDRAIL: a marker with empty numbers is NOT a zero. It happens when the line leaves the engine in a
    state where the number-printer's own interpret() cannot run — measured on the prelude line
    `DUP 0= IF 48 EMIT DROP EXIT THEN`, which is half a definition typed at a prompt and executes EXIT at
    interpret time. Reporting 0 there would be an invented number that sums into a total; None is excluded
    from every sum and printed as `?`.
    """
    os.write(fd, line.encode() + b"\r")
    buf = b""
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if not r:
            continue
        buf += os.read(fd, 4096)
        m = MARK.search(buf)
        if m:
            cyc = int(m.group(1)) if m.group(1) else None
            dsp = int(m.group(2)) if m.group(2) else None
            return cyc, dsp, buf.decode("ascii", "replace")
    raise TimeoutError("no marker for %r; got %r" % (line, buf[-300:]))


def lines_of(path):
    out = []
    for raw in open(path, "r", encoding="utf-8"):
        s = raw.strip()
        if not s or s.startswith("\\"):
            continue
        if len(s) > TIBSZ - 2:
            raise SystemExit("%s: line is %d chars, over TIBSZ %d: %s" % (path, len(s), TIBSZ, s))
        out.append(s)
    return out


def main(argv):
    files = argv[1:]
    if not files:
        raise SystemExit("usage: device_bench.py <prelude.fs> <workload.fs> ...")
    fd = open_port()
    time.sleep(2.0)
    drain(fd, quiet=1.0)
    # GUARDRAIL: prove the instrument is live before measuring. A build without P52_LINECYC answers the probe
    # and produces no marker, and every later timeout would look like a board fault rather than a wrong image.
    for _ in range(6):
        try:
            send_line(fd, "2 3 + .", timeout=5.0)
            break
        except TimeoutError:
            drain(fd, quiet=0.5)
    else:
        raise SystemExit("no marker from '2 3 + .' — is this the P52_LINECYC image?")
    print("%-22s %-6s %10s %8s" % ("file", "line", "cycles", "dispatches"))
    print("%-22s %-6s %10s %8s" % ("-" * 22, "-" * 6, "-" * 10, "-" * 8))
    for path in files:
        tot_c = tot_d = 0
        last = None
        for i, s in enumerate(lines_of(path), 1):
            drain(fd, quiet=0.05)
            cyc, dsp, echo = send_line(fd, s)
            if cyc is None:
                print("%-22s %-6d %10s %8s  %s" % (os.path.basename(path), i, "?", "?", s[:44]))
                continue
            tot_c += cyc
            tot_d += dsp
            last = (cyc, dsp)
            print("%-22s %-6d %10d %8d  %s" % (os.path.basename(path), i, cyc, dsp, s[:44]))
            sys.stdout.flush()
        name = os.path.basename(path)
        print("%-22s %-6s %10d %8d  ALL LINES" % (name, "", tot_c, tot_d))
        if last:
            print("%-22s %-6s %10d %8d  LAST LINE (driver call)"
                  % (name, "", last[0], last[1]))
        print()
    os.close(fd)


if __name__ == "__main__":
    main(sys.argv)
