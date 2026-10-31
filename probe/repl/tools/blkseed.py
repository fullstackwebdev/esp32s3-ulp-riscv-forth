#!/usr/bin/env python3
"""blkseed.py — write a source file into the ULP block store over the REPL.

Test 2 needs phases of 12-16 blocks each; typing C! pokes by hand is hours per phase. This tool sends
blank + pokes + UPDATE + SAVE per block, exactly the path a person would use, so what it seeds is what the
engine's own block layer will read back (no host-side shortcut, no file injected into blkfile[]).

Usage:  python3 tools/blkseed.py --port /dev/ttyACM1 --first 4 src/phase_a.fs
        python3 tools/blkseed.py --port /dev/ttyACM1 --first 4 --verify src/phase_a.fs

GUARDRAIL: 6 bytes per poke line, not 12. The chip's TIBSZ is 96, and a poke is `N W K + C!` = 10-12 chars,
so 6 pokes is ~85 chars and 7 is ~100 - over the limit. Exceeding it is loud (MSG_LINE_TOO_LONG) but the
line is then DROPPED, which would silently seed a block with holes; that is why this refuses to build a line
longer than 88 characters instead of trusting the limit.
"""
import argparse, os, select, sys, termios, time

POKE_LEN = 6          # characters written per line
MAX_LINE = 88         # well under TIBSZ 96


class Repl:
    def __init__(self, port, baud=115200):
        self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
        a = termios.tcgetattr(self.fd)
        a[0] = a[1] = 0
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        a[3] = 0
        a[4] = a[5] = baud
        a[6][termios.VMIN] = 0
        a[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, a)
        self.drain(1.2)

    def drain(self, quiet=0.35, cap=6.0):
        buf, end, last = b"", time.time() + cap, time.time()
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if r:
                c = os.read(self.fd, 4096)
                if c:
                    buf += c
                    last = time.time()
            elif time.time() - last > quiet:
                break
        return buf.decode("ascii", "replace")

    def line(self, text):
        """Send one line, return its output with the echo and the ok/err removed."""
        if len(text) > MAX_LINE:
            raise SystemExit(f"blkseed: refusing a {len(text)}-char line (limit {MAX_LINE}): {text[:40]}...")
        os.write(self.fd, text.encode() + b"\r")
        out = self.drain()
        return out.replace(text, "").replace("\r", "").replace("\n", " ").strip()

    def cmd(self, text, expect_ok=True):
        out = self.line(text)
        if expect_ok and ("?" in out or "ERR_" in out):
            raise SystemExit(f"blkseed: '{text}' failed on the chip: {out!r}")
        return out


def pokes_for(chunk, offset):
    lines = []
    for start in range(0, len(chunk), POKE_LEN):
        part = chunk[start:start + POKE_LEN]
        lines.append(" ".join(f"{ord(c)} W {offset + start + i} + C!" for i, c in enumerate(part)))
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--port", default="/dev/ttyACM1")
    ap.add_argument("--first", type=int, default=4, help="first block number to write")
    ap.add_argument("--verify", action="store_true", help="read every block back and compare")
    args = ap.parse_args()

    text = open(args.file, "rb").read()
    blocks = [text[i:i + 128] for i in range(0, len(text), 128)] or [b""]
    print(f"blkseed: {len(text)} bytes -> {len(blocks)} blocks starting at {args.first}")

    r = Repl(args.port)
    r.cmd("0 BLOCK CONSTANT W")                    # the window address, from the engine
    r.cmd(": B 0 BEGIN DUP 128 < WHILE 32 OVER W + C! 1 + REPEAT DROP ;")

    for k, chunk in enumerate(blocks):
        blk = args.first + k
        r.cmd(f"{blk} BLOCK DROP")                 # fetch the target block into the window
        r.cmd("B")                                 # blank it: LOAD interprets all 128 bytes
        off = 0
        for line in pokes_for(chunk, 0):
            r.cmd(line)
            off += POKE_LEN
        r.cmd("UPDATE")
        out = r.line("SAVE .")
        if "0" not in out:
            raise SystemExit(f"blkseed: SAVE of block {blk} answered {out!r}")
        print(f"  block {blk}: {len(chunk)} bytes saved")

    if args.verify:
        bad = 0
        for k, chunk in enumerate(blocks):
            blk = args.first + k
            r.cmd(f"{blk} BLOCK DROP")
            for i, c in enumerate(chunk):
                out = r.line(f"W {i} + C@ .")
                if out.split()[-1] != str(c):
                    print(f"  VERIFY block {blk} byte {i}: want {c} got {out!r}")
                    bad += 1
        print(f"  verify: {bad} mismatches")
        if bad:
            raise SystemExit(1)
    os.close(r.fd)


if __name__ == "__main__":
    main()
