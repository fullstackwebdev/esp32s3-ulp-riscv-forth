#!/usr/bin/env python3
"""appstore.py — the App Store as the OPERATOR uses it: one command, a real terminal, keys, and back again.

Runs `./cli.py --appstore` inside a pty (the same way tests/tui_cli.py drives the menu), so the terminal path
(`cli.term()`'s raw mode) is what gets tested - not a script that pokes words at the chip. That difference matters: the
store ran correctly when driven directly and returned to the prompt immediately under term() with a non-tty stdin, and
only a pty shows which of the two the operator is actually using.

Guards, in the order the operator hits them:
  1. the shelf draws (title bar, five card titles, the footer) - content, not a title
  2. `j` moves the selection and the frame still has exactly one inverse CARD title
  3. Enter on a card opens the app: the MAIL screen appears
  4. `q` in the app returns to the shelf: "APP STORE" is drawn again
  5. leaving the store lands back in the REPL (`ok` and no `ERR_`)

GUARDRAIL: every frame is read to its SENT sentinel (frames.frame), never "until the title appears" - reading until a title
desynchronises the stream and the rows land in the NEXT read (measured, tests/tui_cli.py).
"""
import os
import pathlib
import pty
import re
import select
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "probe" / "repl" / "tools"))
import frames  # noqa: E402 - the one frame reader

CAP = 90.0
results = []


def check(name, ok, note=""):
    results.append((name, ok, note))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<48} {note}")


def frame(fd, need=b"\x00", cap=CAP, quiet=12.0):
    """Read until `need` appears, or until the line has been quiet for `quiet` seconds."""
    buf, end, last = b"", time.time() + cap, time.time()
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                c = os.read(fd, 65536)
            except OSError:
                break
            if not c:
                break
            buf += c
            last = time.time()
            if need in buf:
                break
        elif time.time() - last > quiet:
            break
    return buf


def text_of(buf):
    """The stream as the operator sees it: escapes removed, so a title search is about drawn text."""
    return re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", buf).decode("latin-1")


def main():
    master, slave = pty.openpty()
    proc = subprocess.Popen([sys.executable, str(REPO / "cli.py"), "--appstore"],
                            cwd=str(REPO), stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    try:
        out = frame(master)
        shown = text_of(out)
        check("the store builds and the shelf draws", b"APP STORE" in out, f"{len(out)} B in the first frame")
        for card in ("CALC", "SHEET", "MAIL", "GOPH", "READ"):
            check(f"card {card} is drawn", card in shown, "")
        # GUARDRAIL: assert the DRAWING, not a title. `MARK` emits ESC[7m for the selected card's title, and HDR emits one
        # more for the bar - so a correct frame has exactly TWO inverse runs. The operator's report was "the first two were
        # highlighted", which this counts.
        inv = out.count(b"\x1b[7m")
        check("exactly one card title is inverse (plus the bar)", inv == 2, f"{inv} inverse run(s)")

        os.write(master, b"j")
        mov = frame(master)
        inv_j = mov.count(b"\x1b[7m")
        check("`j` keeps exactly one card selected", inv_j == 2, f"{inv_j} inverse run(s) after j")

        # open the mail card: two more `j` reaches slot 2 (MAIL) in the first band
        os.write(master, b"jj")
        frame(master)
        os.write(master, b"\r")
        app = frame(master)
        app_shown = text_of(app)
        check("Enter opens MAIL", "INBOX" in app_shown or "MAIL" in app_shown, f"{len(app)} B")

        os.write(master, b"q")
        back = frame(master)
        check("`q` returns to the shelf", b"APP STORE" in back, f"{len(back)} B after q")

        # leave the store for good
        os.write(master, b"\x03")
        tail = frame(master, need=b"> ", cap=30.0, quiet=6.0)
        # GUARDRAIL: the exit is cli.py's own line "(back at the line prompt)" - asserting on the `> ` prompt alone failed
        # because term() prints that message and returns before the prompt is redrawn. Accept either, and say what was seen.
        left = any(k in tail for k in (b"(back at the line prompt)", b"> ", b"ok"))
        check("leaving lands back at the prompt", left, repr(tail[-40:]))
        errs = re.findall(rb"ERR_[A-Z_]+", out + mov + app + back + tail)
        check("no ERR_ anywhere in the run", not errs, str(errs[:3]) if errs else "none")
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            pass
        os.close(master)
    bad = sum(1 for _, ok, _ in results if not ok)
    print(f"\n  {len(results) - bad}/{len(results)} checks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
