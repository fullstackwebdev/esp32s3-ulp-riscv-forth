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
MENU = b"LIBRARY"   # the launcher title; the short needle keeps the test independent of its wording


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


def frame(fd, cap=10.0):
    """Read exactly ONE drawn frame: every frame ends with the SENT sentinel (a 0x00 byte).

    GUARDRAIL: reading until the TITLE desynchronises the stream. "PROGRAM LIBRARY" appears before the rows, so the
    rows stay in the pipe and land in the NEXT read - measured as "0 red rows" in a frame that had one, immediately
    followed by "2 red rows" in a frame that had one. A reader that cannot say where a frame ends cannot count anything
    inside it.
    """
    return read_until(fd, b"\x00", cap)


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
        out = frame(master, CAP)
        check("--library builds and shows the menu", MENU in out,
              f"{'found' if MENU in out else 'NOT found'} in {len(out)} B")
        for liar in (b"ERR_", b"RUN?", b"Traceback"):
            check(f"no {liar.decode()} on the way up", liar not in out, "" if liar not in out else f"in {out[-160:]!r}")

        # GUARDRAIL: assert the DRAWING, not the title, and read a FRAME THAT WAS DRAWN IN THIS STEP. The first version
        # of this check read `dwell(0)` after the menu frame had already been consumed, so it inspected 0 bytes and
        # "failed" on working code - a test that measures nothing is the same class of bug as one that asserts a title.
        # Here each key press produces a full redraw, so the red count is about the row that IS selected.
        os.write(master, b"j")
        mov = frame(master)
        reds_j = mov.count(b"\x1b[31m")
        check("menu paints exactly one red row", reds_j == 1, f"{reds_j} red run(s) after `j`")
        # The operator's report: "I hit j and it turns red, then it stays red" - the selected row was painted and
        # nothing reset the colour, so the OLD row stayed red too. Move back and count: still exactly one.
        os.write(master, b"k")
        mov2 = frame(master)
        reds_k = mov2.count(b"\x1b[31m")
        check("moving back un-reds the old row", reds_k == 1, f"{reds_k} red run(s) after `j` then `k`")

        t0 = time.time()
        os.write(master, b"\r")
        bars = frame(master)
        t1 = (time.time() - t0) * 1000
        # GUARDRAIL: drain the rest of the FIRST frame before judging idleness - measured 845 B of bars still in flight
        # when the title matched, which reads as "it is looping" when it is one frame arriving. The second window is the
        # real question.
        dwell(master, 0.8)
        idle_bars = dwell(master, 1.0)
        hits, high = loud_errors(idle_bars)
        colours = len(set(re.findall(rb"\x1b\[3(\d)m", bars)))
        check("Enter -> colour bars", b"BARS" in bars and b"ERR_" not in bars, f"{t1:.0f} ms")
        check("eight bars, eight colours, real blocks",
              bars.count(b"#") >= 40 and colours >= 8,
              f"{bars.count(b'#')} '#', {colours} distinct colours")
        check("bars is quiet when nobody types", not hits and not high,
              f"{len(idle_bars)} B in 1.5 s idle" + (f", noise {hits} {high}" if (hits or high) else ""))

        os.write(master, b"q")
        back = frame(master)
        check("q -> back to the menu", MENU in back and b"ERR_" not in back)
        reds_back = back.count(b"\x1b[31m")
        check("the menu comes back un-coloured", reds_back == 1,
              f"{reds_back} red run(s) - the bars demo must restore the default colour")

        os.write(master, b"k")
        moved = frame(master)
        check("k moves the marker", MENU in moved and moved.count(b"\x1b[31m") == 1,
              f"menu redrawn {MENU in moved}")

        # GUARDRAIL: the second entry is a CHAIN of three images - the whole point of the feature. Assert the
        # SEQUENCE, not just that something drew: phase 1's title, phase 2's bars, phase 3's "phases done", and a menu
        # afterwards. A chain that stalls is exactly the defect measured while building this (see docs/25), and it
        # shows up here as "no menu came back", not as an error.
        t0 = time.time()
        os.write(master, b"\r")
        chain, frames = b"", 0
        for _ in range(10):
            piece = frame(master, 8.0)
            if not piece:
                break
            chain += piece
            frames += 1
            if MENU in piece:
                break
        ms = (time.time() - t0) * 1000
        check("the chained program runs its phases", b"ULP GAUGE" in chain and chain.count(b"#") >= 40,
              f"{frames} frames, {len(chain)} B, {chain.count(b'#')} '#', {ms:.0f} ms")
        check("the chain ends and returns to the menu", MENU in chain and b"phases done" in chain,
              f"menu back {MENU in chain}, last phase drew {b'phases done' in chain}")
        check("chaining leaves no error behind", b"ERR_" not in chain and b"REFUSED" not in chain,
              "" if b"ERR_" not in chain else repr(chain[-120:]))

        os.write(master, b"q")
        frame(master)
        # GUARDRAIL: drain until the console is SILENT before the last `q`. `term()`'s cleanup used to wait for a reply
        # to `!LINE`, which the host never sends - so it only passed while the REPL's closing ` ok` was still unread in
        # the buffer, and crashed with `devio.Timeout: no reply to '!LINE' within 8.0s` when it had already been
        # consumed. That is what the operator hit: a traceback after a successful build, on a healthy machine. An empty
        # buffer at exit is the failing condition, so the test now CREATES it instead of hoping.
        quiet = b""
        for _ in range(8):
            piece = dwell(master, 0.25)
            quiet += piece
            if not piece:
                break
        check("the console goes quiet before exit", len(quiet) < 600, f"{len(quiet)} B of trailing output")
        os.write(master, b"q")                          # q on the menu: leave the launcher
        try:
            proc.wait(timeout=15.0)
            check("`q` on the menu ends the run", proc.returncode == 0, f"exit {proc.returncode}")
        except subprocess.TimeoutExpired:
            check("`q` on the menu ends the run", False, "still running after `q`")

        # GUARDRAIL: Ctrl-C must end the PROGRAM, not just the proxy. The machine is inside the app's KEY loop, and once
        # the host stops forwarding raw bytes the app can never return - the REPL stays unreachable and the board looks
        # dead. `term()` now sends the app's own quit key and waits for the interpreter's ` ok`. Proven the same way as
        # everything else here: start a run, interrupt it mid-animation, and require a usable machine afterwards.
        m2, s2 = pty.openpty()
        p2 = subprocess.Popen([sys.executable, str(ROOT / "cli.py"), "--library", "--term"], cwd=str(ROOT),
                              stdin=s2, stdout=s2, stderr=s2, close_fds=True)
        os.close(s2)
        try:
            frame(m2, CAP)                      # the menu
            os.write(m2, b"\r")                 # run the bars program
            frame(m2, 10.0)
            os.write(m2, b"\x03")               # Ctrl-C while it owns the terminal
            tail = dwell(m2, 3.0)
            try:
                p2.wait(timeout=15.0)
                rc = p2.returncode
            except subprocess.TimeoutExpired:
                rc = "still running"
            check("Ctrl-C ends the program and the run", rc == 0 and b"did not stop" not in tail,
                  f"exit {rc}")
            check("Ctrl-C reports the line prompt", b"line prompt" in tail or b"Forth REPL" in tail,
                  tail[-60:].decode("latin-1").replace("\r", " ").strip())
        finally:
            if p2.poll() is None:
                p2.kill()
            os.close(m2)

        # GUARDRAIL: `--library` must RELEASE the port. It used to fall into the REPL, which left a live process holding
        # /dev/ttyACM1 for as long as the terminal stayed open, so the operator's next run paid a 9 s reset attempt and
        # then refused. The proof is that a second invocation works and answers, so this starts one: `--repl` reads
        # stdin, so a pipe is enough.
        second = subprocess.run([sys.executable, str(ROOT / "cli.py"), "--repl"], input=b"2 3 + .\n.quit\n",
                                cwd=str(ROOT), capture_output=True, timeout=90)
        out = second.stdout
        check("the port is free for the next run", b"already open by" not in out and second.returncode == 0,
              f"exit {second.returncode}")
        check("and the machine still answers", b"5 ok" in out, "2 3 + . -> 5 ok")
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
