#!/usr/bin/env python3
"""cli.py - start the ULP Forth terminal app. No coding required.

The application itself runs on the ESP32-S3's ULP coprocessor: it writes the alternate screen, the colours,
the cursor moves and reads your single keystrokes. This file is only the pipe between your terminal and the
chip (plus first-time setup: seeding the blocks and compiling them).

    ./cli.py              full-screen app
    ./cli.py --selftest   check the app source splits into legal blocks (no board needed)
    ./cli.py --demo K     non-interactive: start the app, press keys, print what the chip drew
"""
import os
import pathlib
import select
import sys
import termios
import time
import tty

ROOT = pathlib.Path(__file__).resolve().parent
PROBE = ROOT / "probe" / "repl"
sys.path.insert(0, str(PROBE / "tools"))
sys.path.insert(0, str(PROBE))

APP = ROOT / "examples" / "terminal_demo.fs"
FIRST_BLOCK = 64                      # 64..104 belong to the demo app
PORT = os.environ.get("PORT", "/dev/ttyACM1")
CYA, YEL, OFF = "\033[36m", "\033[33m", "\033[0m"


def say(s="", c=""):
    print(f"{c}{s}{OFF if c else ''}", flush=True)


def blocks():
    from fsplit import split_defs
    return split_defs(APP.read_text(), 92)


def prepare(dev, loud=True):
    """Seed and compile the app on the board. One LOAD per line: the machine runs the rest of a line
    before an armed block, so two LOADs on one line silently skip the first one."""
    bs = blocks()
    # GUARDRAIL: after a fresh flash the ULP's .bss still holds the previous image's values (the RTC "already
    # booted" magic survives a reset), so the FIRST line can answer ERR_STACK or ERR_DIRTY. One throwaway line
    # plus the documented block-abort absorbs it instead of letting the operator meet it.
    dev.cmd("0 2 BLKXFER", timeout=8.0, allow_error=True)
    missing = dev.seed_many([(FIRST_BLOCK + i, b) for i, b in enumerate(bs)])
    if missing:
        raise RuntimeError(f"could not write block(s) {missing}")
    for i in range(len(bs)):
        dev.cmd(f"{FIRST_BLOCK + i} LOAD", timeout=20.0, allow_error=True)
    if loud:
        say(f"  {len(bs)} blocks written and compiled by the chip.", CYA)
    return len(bs)


def start(dev):
    """Start the app and hand the keyboard to the chip.

    GUARDRAIL: `!RAW` must be sent AFTER the line that starts the program. It switches the board from line
    assembly to raw byte forwarding; sent first, the program's own start line would be forwarded byte by byte
    and never executed as a line (measured: KEY . answered nothing).
    """
    dev.cmd("!RAW", timeout=8.0, allow_error=True) if False else None
    dev.cmd("RUN", timeout=5.0, allow_error=True)
    dev.cmd("!RAW", timeout=8.0, allow_error=True)


def stop(dev):
    dev.cmd("!LINE", timeout=8.0, allow_error=True)


def proxy(dev):
    """Copy bytes both ways until q. The chip echoes nothing; it redraws the screen itself."""
    fd_in = sys.stdin.fileno()
    old = termios.tcgetattr(fd_in)
    try:
        tty.setraw(fd_in)
        while True:
            r, _, _ = select.select([fd_in, dev.fd], [], [], 0.2)
            if fd_in in r:
                b = os.read(fd_in, 1)
                if not b:
                    break
                os.write(dev.fd, b)
                if b in (b"q", b"Q", b"\x03"):
                    time.sleep(0.4)          # let the chip finish its exit sequence
                    break
            if dev.fd in r:
                try:
                    os.write(sys.stdout.fileno(), os.read(dev.fd, 4096))
                except OSError:
                    pass
    finally:
        termios.tcsetattr(fd_in, termios.TCSADRAIN, old)


def main(argv):
    if "--selftest" in argv:
        bs = blocks()
        print(f"  app: {len(bs)} blocks, largest {max(len(b) for b in bs)} B, fits: {all(len(b) <= 128 for b in bs)}")
        return 0

    from devio import Dev
    try:
        dev = Dev(port=PORT)
        dev.reset()
    except Exception:
        say(f"  No board on {PORT}.", YEL)
        say("  * is the USB cable in?", YEL)
        say("  * Linux: sudo usermod -aG dialout $USER  (log out, log in)", YEL)
        say("  * other port: PORT=/dev/ttyACM0 ./cli.py", YEL)
        return 2

    try:
        prepare(dev)
        if "--demo" in argv:
            keys = argv[argv.index("--demo") + 1]     # e.g. "jj" then Enter
            dev.cmd("RUN", timeout=5.0, allow_error=True)
            dev.cmd("!RAW", timeout=8.0, allow_error=True)
            for ch in keys:
                os.write(dev.fd, ch.encode())
                time.sleep(0.6)
            time.sleep(0.5)
            out = b""
            while True:
                r, _, _ = select.select([dev.fd], [], [], 0.3)
                if not r:
                    break
                out += os.read(dev.fd, 4096)
            sys.stdout.write(out.decode(errors="replace"))
            dev.cmd("!LINE", timeout=8.0, allow_error=True)
            return 0

        say()
        say("  The app draws itself on the chip. Keys: j/k move, Enter = refresh, q quit.", CYA)
        input("  press Enter to start... ")
        start(dev)
        proxy(dev)
        stop(dev)
        say("\n  back at your shell.", CYA)
        return 0
    finally:
        dev.close()


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print()
        sys.exit(0)
