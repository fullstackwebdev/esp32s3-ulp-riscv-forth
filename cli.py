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


def port_holders(port):
    """Who else has this tty open. Linux answers in /proc, and "the board is dead" vs "something else holds the cable"
    are different facts with different fixes.

    GUARDRAIL: measured the hard way - a crashed test harness left `cli.py --library` alive on /dev/ttyACM1, and every
    later run spent 21-36 s retrying resets and then said "the board did not come back to a fresh dictionary". That
    message sent me looking at hardware for a bug in a process table.
    """
    try:
        st = os.stat(port)
    except OSError:
        return ""
    me = {os.getpid(), os.getppid()}
    found = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) in me:
            continue
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                try:
                    s = os.stat(f"/proc/{pid}/fd/{fd}")
                except OSError:
                    continue
                if s.st_ino == st.st_ino and s.st_rdev == st.st_rdev:
                    cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode("latin-1").strip()
                    found.append(f"pid {pid} ({cmd[:60]})")
                    break
        except OSError:
            continue
    return ", ".join(found)


def connect(port, settle):
    from devio import Dev
    # GUARDRAIL: ask who holds the port BEFORE any reset. This check used to sit after `pulse_reset`, which - now that a
    # pulse is verified and falls back - spent ~9 s resetting a port it could never reach, and only then named the other
    # process. Measured: a stale `cli.py` from a previous run made every later run pay 9 s and then refuse.
    holders = port_holders(port)
    if holders:
        say(f"  {port} is already open by: {holders}", YL)
        say("  close that program (or kill it) and run this again.", YL)
        return None
    try:
        dev = Dev(port=port)
        # GUARDRAIL: go straight to the esptool reset. On this board the DTR/RTS pulse is a no-op (USB-Serial-JTAG
        # emulates the modem bits, F-126), so paying for a pulse first bought 1.3 s and a fallback every single run.
        dev.reset(settle=0.25)
    except Exception:
        say(f"no board on {port}.", YL)
        say("  * cable in?  * Linux: sudo usermod -aG dialout $USER (log out, in)", YL)
        say("  * other port: PORT=/dev/ttyACM0 ./cli.py", YL)
        return None
    # GUARDRAIL: after a hard reset the ULP may still be booting, and .bss carries the previous image's block state
    # (the RTC "already booted" magic survives a reset). Both showed up as a FIRST command that timed out or answered
    # ERR_STACK/ERR_DIRTY. Retry, then clear the block latch by name.
    # GUARDRAIL: a reset that did not happen must not be accepted as one. Measured, twice: an RTS pulse silently does
    # nothing, the still-running ULP answers politely, and the next upload compiles on top of the previous app - the
    # dictionary runs out mid-upload and the operator sees a wall of ERR_DICT from block 70 on, which looks like the app
    # being too big. Assert a FRESH machine (baked HERE ~786 and >900 B free), and fall back to esptool's slower reset.
    #
    # GUARDRAIL: this loop used to burn 21-36 s and then blame the board. The holder check is above (a held port is a
    # different fact from a non-fresh dictionary, with a different fix), the probe timeout is 1.5 s because a live ULP
    # answers `HERE .` in 40 ms - a longer timeout only hides a dead one - and `!LINE` goes first, because a previous
    # session may leave the board in raw mode where a probe is read as a keystroke.
    fresh, answered, here, free = False, False, 0, 0
    for attempt in range(4):
        if attempt:
            say(f"  retrying reset ({attempt + 1}/4)...", DM)
            dev.reset(settle=0.3)
        try:
            dev.cmd("!LINE", timeout=1.5, allow_error=True)
            here = dev.num("HERE .", timeout=1.5)
            free = dev.num("LATEST HERE - .", timeout=1.5)
        except Exception:
            continue
        answered = True
        if here < 900 and free > 900:
            fresh = True
            break
    if not fresh:
        if answered:
            say(f"  the dictionary is not fresh (HERE {here}, {free} B free).", YL)
            say("  unplug the USB cable, plug it back in, and run this again.", YL)
        else:
            say("  the board did not answer at all.", YL)
            say(f"  * is another program holding the port?  (fuser -v {port})", YL)
            say("  * cable in?  * Linux: sudo usermod -aG dialout $USER (log out, in)", YL)
        return None
    dev.cmd("0 2 BLKXFER", timeout=6.0, allow_error=True)
    say(f"  connected: fresh dictionary, {free} B free.", DM)
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
        # GUARDRAIL: `settle=0.004` because a LOAD answers with exactly one line. The 20 ms default per block was 0.7 s
        # of the build's 4.8 s, spent waiting for a second line that never comes.
        rep = dev.cmd(f"{first_block + i} LOAD", timeout=25.0, allow_error=True, settle=0.004)
        errs = [l.strip() for l in rep.splitlines() if l.strip().endswith("?") or "ERR_" in l]
        if errs:
            bad[first_block + i] = errs[0]
        # GUARDRAIL: report EVERY block, not every tenth. Seven seconds of silence is what "really slow" feels like, and
        # the operator cannot tell a slow build from a wedged board - measured complaint, twice.
        sys.stdout.write(f"\r  compiling {i + 1}/{len(bs)} blocks"); sys.stdout.flush()
    sys.stdout.write("\r" + " " * 40 + "\r")
    say(f"  {path}: {len(bs)} blocks, {time.time() - t0:.1f} s", DM)
    for blk, err in bad.items():
        say(f"  block {blk}: {err}", YL)          # named, never swallowed
    return len(bs), bad


LIB_FIRST, DEMO_FIRST = 70, 30          # launcher source; demo source is reused for every build
LIBRARY = (("examples/demo_bars.fs", 50, "RUNB"), ("examples/demo_spin.fs", 60, "RUNS"))


def library(dev, root):
    """Build the program library: a resident launcher, then each demo as a behaviour image.

    Returns the built descriptors ({path, desc, cs, ce, entry}), or None after printing why it refused. Callers
    (tests/programs.py, tests/tui_cli.py) assert on the returned values instead of re-deriving them: two copies of
    "what a good image looks like" is how one of them silently stops checking anything (R6).

    GUARDRAIL: order is the whole trick. The launcher is compiled FIRST and sealed, so it stays resident while `BLKXFER`
    op 3 rewinds the dictionary over the demos - code that performs an adopt cannot live in the region it replaces.
    GUARDRAIL: rewind before every demo build. Without it the second demo is compiled on top of the first, the image
    spans both, and adopting it runs whatever happened to be compiled last.
    GUARDRAIL: the rewind is `RW` (the launcher's own `bh @ VH ! bl @ VL !`), NOT `2 OVL`. `OVL` is `( blk -- )`: it
    rewinds AND arms a block as the interpreter's source, so inside a running word it queues a block to be COMPILED
    instead of returning to the seal. It happened to work from the console and is wrong everywhere else.
    """
    here = dev.num("HERE .")
    if here > 900:
        # GUARDRAIL: a library built onto a non-fresh dictionary fails later as `ERR_DICT` in the middle of an upload,
        # which reads like "the app is too big". Refuse here with the reason instead.
        say(f"  the machine already has a program loaded (HERE {here}); reset it first", YL)
        return None
    n, bad = upload(dev, str(root / "examples/menu.fs"), LIB_FIRST)
    if bad:
        return None
    dev.cmd("SEAL")
    base = dev.num("bh @ .")
    say(f"  launcher sealed at {base} ({n} blocks)", DM)
    built = []
    for path, desc, entry in LIBRARY:
        dev.cmd("RW")                           # back to the seal, so this demo owns the space above it
        n, bad = upload(dev, str(root / path), DEMO_FIRST)
        if bad:
            return None
        cs, ce = dev.num("bh @ ."), dev.num("HERE .")
        hs, he = dev.num("LATEST ."), dev.num("bl @ .")
        ent = dev.num(f"' {entry} .")
        # GUARDRAIL: a stub image is what a failed LOAD leaves behind (measured: 10 B), and EXECUTE then jumps into
        # never-compiled bytes and spins with no error at all. The stub that actually hung the machine was 10 B, and a
        # legitimate demo was once 92 B, so the minimum is 48 B - not the 120 B a phase-sized heuristic guessed.
        if cs != base or ce - cs < 48 or not (cs <= ent < ce):
            say(f"  {path}: code {cs}..{ce} ({ce - cs} B) entry {ent} - not buildable above the seal at {base}", YL)
            return None
        dev.cmd(f"#d {desc} {cs} {ce} {hs} {he} {ent}")
        built.append(dict(path=path, desc=desc, cs=cs, ce=ce, entry=ent, blocks=n))
        say(f"  {path}: {ce - cs} B of code -> block {desc}, entry {ent}", DM)
    dev.cmd("RW")
    say(f"  library ready: {len(LIBRARY)} programs; Enter runs one, q returns, q on the menu quits", CY)
    return built


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
                if os.environ.get("DEBUG"):
                    say(f"  [term] stdin {b!r}", DM)
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
                # GUARDRAIL: this break means "the PROGRAM restored the screen". It fired on the very first frame of a
                # working launcher, and the trace below is what shows whether the program or this host exited.
                if os.environ.get("DEBUG"):
                    rest = b"\x1b[?1049l" in chunk
                    say(f"  [term] chunk {len(chunk)}B restore={rest}", DM)
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
    ap.add_argument("--library", action="store_true",
                    help="build the program library (resident launcher + demo images) and run the menu")
    ap.add_argument("--repl", action="store_true",
                    help="after --library's app exits, stay in the REPL instead of leaving (it holds the port)")
    ap.add_argument("--block", type=int, default=64, metavar="N", help="first block to use (default 64)")
    ap.add_argument("--port", default=os.environ.get("PORT", "/dev/ttyACM1"))
    ap.add_argument("--settle", type=float, default=1.0, help="seconds to wait after reset (default 1.0)")
    a = ap.parse_args()
    if a.library and a.include:
        ap.error("--library builds its own sources; do not combine it with -i")

    dev = connect(a.port, a.settle)
    if not dev:
        return 2
    try:
        blk = a.block
        failed = False
        if a.library:
            root = pathlib.Path(__file__).resolve().parent
            if not library(dev, root):
                return 1
            # GUARDRAIL: `--term`'s default (const) is `RUN`, and the launcher has no such word - the menu's entry is
            # `RUNP`. Left as RUN, the terminal was handed over and the machine answered `RUN?` into an invisible
            # screen: the tool looked hung on its own menu. `--library` therefore RUNS the menu unless a word is given.
            if a.term is None or a.term == "RUN":
                a.term = "RUNP"
        for path in a.include:
            n, bad = upload(dev, path, blk)
            blk += n
            failed = failed or bool(bad)
        if failed:
            # GUARDRAIL: do not start the program after a failed compile. The word it needs is missing, so --term would
            # show an empty screen with no explanation - and the operator would blame the app rather than the upload.
            say("  upload had errors - fix them above, then run again.", YL)
            return 1
        if a.term is not None:
            term(dev, a.term)
            # GUARDRAIL: `--library` RUNS the library; when the app exits, the run is over. Dropping into the REPL left a
            # live process holding /dev/ttyACM1 for as long as the terminal stayed open, so the NEXT `./cli.py --library`
            # had to be told "already open by pid ...". Measured: the operator's second run paid a 9 s reset attempt and
            # then refused. Staying is available, explicitly: `--repl`.
            if a.library and not a.repl:
                return 0
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
