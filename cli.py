#!/usr/bin/env python3
"""cli.py - talk to the Forth machine on the ESP32-S3 ULP through its serial TTY.

    ./cli.py                       interactive Forth REPL
    ./cli.py -i app.fs             upload a program (split into blocks, compiled on the chip) then REPL
    ./cli.py -i app.fs --term RUN  upload, then hand the whole terminal to the program

REPL commands (start with a dot, handled here, not by the chip):
    .help              this list
    .term [WORD]       give the terminal to a running program (optional WORD is sent first, e.g. .term RUN)
    .load FILE         upload another program now
    .status            block store state: blocks, erases, wear
    .quit              leave
Anything else is sent to the chip as Forth. Ctrl-C always gives your terminal back.
"""
import argparse
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

CY, YL, DM, OFF = "\033[36m", "\033[33m", "\033[2m", "\033[0m"
# GUARDRAIL: these three sequences are the whole reason a crashed session can ruin a terminal. Every exit path -
# .term, Ctrl-C, Ctrl-D, an exception, SIGTERM - must emit all three: leave the alternate screen, show the cursor,
# reset colours. Once a terminal is left in the alternate buffer, the operator's shell "disappears".
RESTORE = "\033[?1049l\033[?25h\033[0m"


def say(s="", c=""):
    print(f"{c}{s}{OFF if c else ''}", flush=True)


def connect(port, settle):
    from devio import Dev
    try:
        dev = Dev(port=port)
        dev.pulse_reset(settle=settle)   # ~50 ms instead of ~2.5 s of esptool
    except Exception:
        say(f"no board on {port}.", YL)
        say("  * cable in?  * Linux: sudo usermod -aG dialout $USER (log out, in)", YL)
        say("  * other port: PORT=/dev/ttyACM0 ./cli.py", YL)
        return None
    # GUARDRAIL: after a hard reset the ULP may still be booting, and .bss carries the previous image's block state
    # (the RTC "already booted" magic survives a reset). Both showed up as a FIRST command that timed out or answered
    # ERR_STACK/ERR_DIRTY. Retry, then clear the block latch by name.
    for _ in range(6):
        try:
            dev.cmd("2 3 + .", timeout=4.0, allow_error=True)
            break
        except Exception:
            time.sleep(0.6)
    dev.cmd("0 2 BLKXFER", timeout=6.0, allow_error=True)
    return dev


def upload(dev, path, first_block):
    """Split a Forth program into legal blocks, write them, and ask the chip to compile them."""
    from fsplit import split_defs
    src = pathlib.Path(path).read_text()
    bs = split_defs(src, 92)
    if first_block + len(bs) > 128:
        raise RuntimeError(f"{len(bs)} blocks from {first_block} would pass block 127, which the server refuses")
    t0 = time.time()
    missing = dev.seed_many([(first_block + i, b) for i, b in enumerate(bs)])
    if missing:
        raise RuntimeError(f"block(s) {missing} did not acknowledge - is the cable loose?")
    bad = {}
    for i in range(len(bs)):
        rep = dev.cmd(f"{first_block + i} LOAD", timeout=25.0, allow_error=True)
        errs = [l.strip() for l in rep.splitlines() if l.strip().endswith("?") or "ERR_" in l]
        if errs:
            bad[first_block + i] = errs[0]
        if (i + 1) % 10 == 0:
            sys.stdout.write(f"\r  compiling {i + 1}/{len(bs)} blocks"); sys.stdout.flush()
    sys.stdout.write("\r" + " " * 40 + "\r")
    say(f"  {path}: {len(bs)} blocks, {time.time() - t0:.1f} s", DM)
    for blk, err in bad.items():
        say(f"  block {blk}: {err}", YL)          # named, never swallowed
    return len(bs), bad


def term(dev, word=None):
    """Hand the terminal to a Forth program: raw bytes in, everything out, full-screen escapes intact."""
    if word:
        # GUARDRAIL: do NOT wait for a reply here. The program starts drawing immediately, and a waiting read would
        # consume the first frame (measured: the alternate screen was entered and restored with nothing drawn).
        os.write(dev.fd, (word + "\r").encode())
        time.sleep(0.05)
    # GUARDRAIL: !RAW must be sent AFTER the word that starts the program. Sent first, the start word itself would be
    # forwarded as raw bytes and never executed as a line. The CR that ends this line is swallowed by the board. This is
    # also written without waiting, for the reason above: whatever the host prints next belongs on the operator's screen.
    os.write(dev.fd, b"!RAW\r")
    time.sleep(0.1)
    fin = sys.stdin.fileno()
    # GUARDRAIL: a piped stdin is not a terminal, and termios.tcgetattr raises ENOTTY - measured while scripting a
    # Ctrl-C test. Terminal modes are applied only when there is a terminal to apply them to; the byte proxy is identical
    # either way, so scripts and CI can drive a full-screen program too.
    interact = os.isatty(fin)
    old = termios.tcgetattr(fin) if interact else None
    try:
        if interact:
            tty.setraw(fin)
        sys.stdout.write("\033[?1049h")           # let the program own a clean alternate screen
        sys.stdout.flush()
        while True:
            r, _, _ = select.select([fin, dev.fd], [], [], 0.2)
            if fin in r:
                b = os.read(fin, 1)
                if not b:
                    break
                if b == b"\x03":                   # Ctrl-C: always ours, never the program's
                    break
                os.write(dev.fd, b)
            if dev.fd in r:
                try:
                    chunk = os.read(dev.fd, 4096)
                except OSError:
                    break
                os.write(sys.stdout.fileno(), chunk)
                if b"\x1b[?1049l" in chunk:        # the program restored the screen: it is done
                    break
    finally:
        if old is not None:
            termios.tcsetattr(fin, termios.TCSADRAIN, old)
        sys.stdout.write(RESTORE)
        sys.stdout.flush()
        dev.cmd("!LINE", timeout=8.0, allow_error=True)
    say("  (back in the REPL)", DM)


def status(dev):
    for ln in dev.cmd("#i", timeout=10.0).splitlines():
        if "info:" in ln:
            say("  " + ln.split("info:", 1)[1].strip(), CY)


def repl(dev, first_block):
    say("  Forth REPL. Lines are limited to 63 characters. .help for commands, .quit to leave.", DM)
    while True:
        try:
            line = input(f"{CY}>{OFF} ")
        except (EOFError, KeyboardInterrupt):
            say()
            return
        s = line.strip()
        if not s:
            continue
        if s in (".quit", ".q", "quit"):
            return
        if s == ".help":
            say("  .term [WORD]  hand the terminal to a program   .load FILE  upload a program", DM)
            say("  .status       block store state                .quit        leave", DM)
            continue
        if s == ".status":
            status(dev)
            continue
        if s.startswith(".term"):
            parts = s.split(None, 1)
            term(dev, parts[1] if len(parts) > 1 else None)
            continue
        if s.startswith(".load"):
            parts = s.split(None, 1)
            if len(parts) < 2:
                say("  usage: .load FILE", YL)
                continue
            try:
                upload(dev, parts[1], first_block)
            except Exception as e:
                say(f"  {e}", YL)
            continue
        if len(s) > 63:
            say(f"  {len(s)} characters - the machine holds 63.", YL)
            continue
        try:
            out = dev.cmd(s, timeout=25.0, allow_error=True)
        except Exception:
            say("  no answer (the machine may be busy or the line was lost)", YL)
            continue
        for ln in out.splitlines():
            if ln.strip() and ln.strip() != s and ln.strip() != "ok":
                print("  " + ln, flush=True)


def main():
    ap = argparse.ArgumentParser(description="Forth REPL and program loader for the ULP machine")
    ap.add_argument("-i", "--include", action="append", default=[], metavar="FILE",
                    help="Forth program to upload and compile (repeatable)")
    ap.add_argument("--term", metavar="WORD", nargs="?", const="RUN", default=None,
                    help="after loading, hand the terminal to the program (default word: RUN)")
    ap.add_argument("--block", type=int, default=64, metavar="N", help="first block to use (default 64)")
    ap.add_argument("--port", default=os.environ.get("PORT", "/dev/ttyACM1"))
    ap.add_argument("--settle", type=float, default=1.0, help="seconds to wait after reset (default 1.0)")
    a = ap.parse_args()

    dev = connect(a.port, a.settle)
    if not dev:
        return 2
    try:
        blk = a.block
        for path in a.include:
            n, bad = upload(dev, path, blk)
            blk += n
        if a.term is not None:
            term(dev, a.term)
        repl(dev, blk)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout.write(RESTORE)                 # never leave the terminal in a strange state
        sys.stdout.flush()
        dev.close()


if __name__ == "__main__":
    sys.exit(main())
