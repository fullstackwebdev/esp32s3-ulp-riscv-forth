#!/usr/bin/env python3
"""tui_cli.py — `./cli.py --library` as the OPERATOR runs it: build, then hand the terminal to the menu.

Why a pty and not a pipe: `term()` proxies the operator's terminal, and it asks `os.isatty(stdin)` before touching
termios. A piped stdin is not a terminal - it also hits EOF the moment the feeder stops writing, which the last
session mistook for "the program restored the screen" and chased for a while. A pty has the two properties a human's
terminal has: it IS a tty, and it does not close when idle.

What it proves, in the operator's own terms:
  * `--library` builds the launcher + both images with no extra flags and no test harness;
  * the menu appears (so `--term` was handed the launcher's entry word, not the group's default `RUN`);
  * Enter runs a program, `q` comes back, `k` picks the other one and it RUNS - the case docs/25 recorded as refused;
  * `q` on the menu returns to the Forth REPL, which still answers;
  * BOTH demos are SILENT while nobody types, and noisy bytes are named - the spinner used to flood
    `ERR_ULPCODE` from its second frame on (an unclamped `48 +` walking into the console's message-code space),
    and `read_until(b"SPIN")` returned before the flood started, so a green run certified it.

GUARDRAIL: `--library` must RUN the menu, not just build it. `--term`'s default is the word `RUN`, which the launcher
does not define, so the shipped command used to hand the terminal to a missing word and print `RUN?` into an invisible
alternate screen - the tool looked hung. That is why the first assertion here is the menu's own title.
"""
import os, sys, pty, re, time, select, pathlib, subprocess, signal

ROOT = pathlib.Path(__file__).resolve().parents[3]
CAP = 40.0
MENU = b"PROGRAM LIBRARY"


def read_until(fd, needle, cap):
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
    """Read for the WHOLE cap, ignoring quiet. A busy-looping program is silent until it is not; the earlier version of
    this test stopped at the first frame that matched a needle and therefore could not see a flood that started after
    it - which is exactly how `ERR_ULPCODE` got past a green run."""
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


def loud_errors(buf):
    """Anything the console should never print while a demo is idle."""
    hits = re.findall(rb"ERR_[A-Z_]+", buf)
    hits += re.findall(rb"ERR_ULPCODE 0x[0-9a-f]+", buf)
    high = sorted({b for b in buf if b >= 0x80})
    return sorted(set(hits)), high


def main():
    results = []

    def check(name, ok, note=""):
        results.append((name, ok, note))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<44} {note}")

    master, slave = pty.openpty()
    proc = subprocess.Popen([sys.executable, str(ROOT / "cli.py"), "--library", "--term"],
                            cwd=str(ROOT), stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    try:
        out = read_until(master, MENU, CAP)
        check("--library builds and shows the menu", MENU in out,
              f"{'found' if MENU in out else 'NOT found'} in {len(out)} B")
        for liar in (b"ERR_", b"RUN?", b"Traceback"):
            check(f"no {liar.decode()} on the way up", liar not in out, "" if liar not in out else f"in {out[-160:]!r}")

        t0 = time.time()
        os.write(master, b"\r")
        bars = read_until(master, b"BARS", 10.0)
        t1 = (time.time() - t0) * 1000
        # GUARDRAIL: drain the rest of the FIRST frame before judging idleness - measured 845 B of bars still in flight
        # when the title matched, which reads as "it is looping" when it is one frame arriving. The second window is the
        # real question.
        dwell(master, 0.8)
        idle_bars = dwell(master, 1.0)
        hits, high = loud_errors(idle_bars)
        check("Enter -> colour bars", b"BARS" in bars and b"ERR_" not in bars, f"{t1:.0f} ms")
        check("bars is quiet when nobody types", not hits and not high,
              f"{len(idle_bars)} B in 1.5 s idle" + (f", noise {hits} {high}" if (hits or high) else ""))

        os.write(master, b"q")
        back = read_until(master, MENU, 10.0)
        check("q -> back to the menu", MENU in back and b"ERR_" not in back)

        os.write(master, b"k")
        moved = read_until(master, MENU, 10.0)
        t0 = time.time()
        os.write(master, b"\r")
        spin = read_until(master, b"SPIN", 10.0)
        t2 = (time.time() - t0) * 1000
        # GUARDRAIL: this is the check that was missing for the whole feature (docs/25). `read_until(SPIN)` returns the
        # moment the title appears, so it certified a program whose FIRST frame was fine and whose second was
        # `ERR_ULPCODE`. Read for the full window instead, and read again with an idle screen.
        idle_spin = dwell(master, 2.0)
        hits, high = loud_errors(idle_spin)
        check("k + Enter -> the OTHER program runs", b"SPIN" in spin and b"ERR_" not in spin,
              f"{t2:.0f} ms; menu redrawn {MENU in moved}")
        check("spinner is quiet when nobody types", not hits and not high,
              f"{len(idle_spin)} B in 2 s idle" + (f", noise {hits[:4]} {high[:6]}" if (hits or high) else ""))

        # A key-paced demo must answer a key with a new frame - otherwise "quiet" could just mean "dead".
        frames = []
        for _ in range(3):
            os.write(master, b"j")
            frames.append(dwell(master, 0.25))
        check("a key advances the spinner", all(b"SPIN" in f for f in frames) and len({f for f in frames}) > 1,
              f"{len(frames)} frames, {sum(len(f) for f in frames)} B")
        hits, high = loud_errors(b"".join(frames))
        check("no noise from keying either", not hits and not high, f"{hits[:4]} {high[:6]}" if (hits or high) else "")

        os.write(master, b"q")
        read_until(master, MENU, 10.0)
        os.write(master, b"q")                          # q on the menu: leave the launcher
        repl = read_until(master, b"Forth REPL", 10.0)
        check("q on the menu returns to the REPL", b"Forth REPL" in repl)

        os.write(master, b"2 3 + .\r")
        got = read_until(master, b"5 ok", 10.0)
        check("the REPL still answers", b"5 ok" in got, "2 3 + . -> 5 ok")

        os.write(master, b".quit\r")
        try:
            proc.wait(timeout=10.0)
            check("cli.py exits cleanly", proc.returncode == 0, f"exit {proc.returncode}")
        except subprocess.TimeoutExpired:
            check("cli.py exits cleanly", False, "still running after .quit")
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        os.close(master)

    bad = sum(1 for _, ok, _ in results if not ok)
    print(f"\n  {len(results) - bad}/{len(results)} checks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
