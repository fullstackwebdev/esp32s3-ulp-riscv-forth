#!/usr/bin/env python3
"""programs.py — the program library: a RESIDENT launcher that adopts demo images and switches between them.

Layout, and why it is the only one that can work in this machine: `BLKXFER` op 3 rewinds the dictionary and copies an
image over it. Any code that ISSUES the adopt is therefore inside the region being replaced - unless it is resident,
below the seal. So: compile the launcher, SEAL, compile each demo above the seal and dump it, rewind, and let the
resident `SWITCH` adopt. The demo ends with `EXIT`, which returns to the resident caller, which redraws the menu.

GUARDRAIL: each demo is ~600 B and lives above the seal; the launcher is ~700 B below it. If the launcher grew past the
demo's start, the adopt would overwrite the very code doing the adopting, and the failure would look like a random hang
inside a working demo, not like a size error.
"""
import os, sys, time, pathlib, select
ROOT = pathlib.Path(__file__).resolve().parents[3]
# GUARDRAIL: ROOT must be on the path before `import cli` - this test drives the SHIPPING build path, and a test that
# cannot see it is how the duplicate build steps crept back in.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "tools")
EX = ROOT / "examples"
SENTINEL = b"\x00"
CAP = 5.0
PORT = os.environ.get("PORT_DEV", "/dev/ttyACM1")


def clean(frame):
    return b"ERR_" not in frame


def read_frame(dev, cap=CAP):
    buf, end = b"", time.time() + cap
    while time.time() < end and SENTINEL not in buf:
        r, _, _ = select.select([dev.fd], [], [], 0.05)
        if r:
            buf += os.read(dev.fd, 8192)
    return buf


def read_until(dev, needle, cap=CAP):
    """Read frames until one contains `needle`.

    GUARDRAIL: after `q` the demo is still mid-redraw, so the FIRST frame received is demo output, not the launcher.
    Reading one frame and asserting on it failed on a working switch; the reporter is "did the launcher frame arrive",
    which means reading until it does (or the cap expires, which keeps a dead program loud).
    """
    buf, end = b"", time.time() + cap
    while time.time() < end:
        buf += read_frame(dev, cap=max(0.05, end - time.time()))
        if needle in buf:
            break
    return buf


def show(frame, n=120):
    t = frame.replace(SENTINEL, b"").decode("latin-1")
    return repr(t[:n])


def main():
    results = []
    import cli          # the SHIPPING build path, not a copy of it: one definition of "a good image" (R6)
    dev = cli.connect(PORT, 1.0)
    if not dev:
        return report([("connect", False, "no board, or the dictionary is not fresh")])
    try:
        free = dev.num("LATEST HERE - .", timeout=5.0)
        results.append(("fresh boot", True, f"here={dev.num('HERE .')} free={free}"))
        dev.cmd("0 2 BLKXFER", timeout=6.0, allow_error=True)

        # GUARDRAIL: the build is cli.library(), the same call `./cli.py --library` makes. This test used to carry its
        # own copy of the steps, which meant the shipped command could break while the test stayed green - and it did:
        # the copy still said `2 OVL`, which is `( blk -- )` and arms a block instead of only rewinding.
        built = cli.library(dev, ROOT)
        results.append(("build the library (cli.library)", bool(built),
                        "; ".join(f"{b['path']}: {b['ce'] - b['cs']} B -> block {b['desc']}" for b in (built or []))))
        if not built:
            raise SystemExit(report(results))
        base = dev.num("bh @ .")
        for b in built:
            results.append((f"{pathlib.Path(b['path']).name}: starts at the seal", b["cs"] == base,
                            f"code {b['cs']}..{b['ce']} ({b['ce'] - b['cs']} B), entry {b['entry']}"))

        os.write(dev.fd, b"RUNP\r"); time.sleep(0.35)
        os.write(dev.fd, b"!RAW\r"); time.sleep(0.25)
        menu = read_frame(dev)
        results.append(("menu frame", b"LIBRARY" in menu and clean(menu), show(menu)))

        t0 = time.time()
        os.write(dev.fd, b"\r")
        b1 = read_frame(dev)
        t1 = time.time() - t0
        results.append(("Enter -> colour bars", b"BARS" in b1 and clean(b1), f"{t1 * 1000:.0f} ms, {show(b1, 60)}"))

        os.write(dev.fd, b"q")
        m2 = read_until(dev, b"LIBRARY")
        results.append(("q -> back to the launcher", b"LIBRARY" in m2 and clean(m2), show(m2, 60)))

        os.write(dev.fd, b"k")          # two entries: toggle to the other one
        m3 = read_until(dev, b"LIBRARY")
        t0 = time.time()
        os.write(dev.fd, b"\r")
        s1 = read_until(dev, b"ULP GAUGE")
        t2 = time.time() - t0
        # GUARDRAIL: this is the check that failed for the whole feature (docs/25). It passed the moment the resident
        # identity stopped being a sum of the LIVE resident region - `k` writes SEL, which lives in it. If this goes red
        # again, read the refusal: `REFUSED resident dictionary changed` means resident_sum() and the writer disagree
        # about what is mutable, NOT that the dictionary changed.
        results.append(("Enter -> gauge (chained program)", b"ULP GAUGE" in s1 and clean(s1),
                        f"{t2 * 1000:.0f} ms, {show(s1, 60)}"))
        results.append(("k moved the marker", b"LIBRARY" in m3 and clean(m3), show(m3, 40)))

        os.write(dev.fd, b"q")
        m4 = read_until(dev, b"LIBRARY")
        results.append(("q -> launcher again", b"LIBRARY" in m4 and clean(m4), show(m4, 60)))

        os.write(dev.fd, b"q")          # quit the launcher
        time.sleep(0.3)
        dev.drain()
        dev.cmd(b"!LINE".decode(), timeout=3.0, allow_error=True)
        got = dev.num("2 3 + .", timeout=5.0)
        results.append(("REPL usable after leaving the TUI", got == 5, f"2 3 + . = {got}"))

        total = (t1 + t2) / 2 * 1000
        print(f"\n  adopt+first frame: bars {t1 * 1000:.0f} ms, spinner {t2 * 1000:.0f} ms, mean {total:.0f} ms")
    finally:
        if any(not ok for _, ok, _ in results):
            dump_state(dev, "(after failure)")
        dev.close()
    return report(results)


def dump_state(dev, note=""):
    """Leave raw mode (the only way to talk to the REPL again) and print the machine's own view.

    GUARDRAIL: a launcher that fails inside raw mode shows the test NOTHING - the keybox eats every byte, so a queued
    `HERE .` is read as a keystroke, not a command. `!LINE` is a host op and works from raw mode (measured), which makes
    the machine inspectable at the exact moment it misbehaved.
    """
    try:
        dev.cmd("!LINE", timeout=3.0, allow_error=True)
        time.sleep(0.2)
        print(f"  state{(' ' + note) if note else ''}: HERE={dev.num('HERE .')} LATEST={dev.num('LATEST .')} "
              f"bh={dev.num('bh @ .')} bl={dev.num('bl @ .')}")
    except Exception as e:
        print(f"  state{(' ' + note) if note else ''}: unreachable ({type(e).__name__})")


def report(results):
    print()
    for name, ok, note in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<38} {note}")
    bad = sum(1 for _, ok, _ in results if not ok)
    print(f"\n  {len(results) - bad}/{len(results)} checks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
