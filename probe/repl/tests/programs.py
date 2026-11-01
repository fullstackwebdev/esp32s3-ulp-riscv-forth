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
sys.path.insert(0, "tools")
from devio import Dev
from fsplit import split_defs

ROOT = pathlib.Path(__file__).resolve().parents[3]
EX = ROOT / "examples"
MENU_FIRST, MENU_BLOCKS = 70, 30        # launcher source, compiled, then SEALed
DEMO_FIRST = 30                          # demo source is re-used for each build
BARS_DESC, SPIN_DESC = 50, 60            # 5 blocks each
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


def compile_file(dev, path, first, name, results):
    blocks = split_defs(path.read_text(), 92)
    assert first + len(blocks) <= 128, f"{name}: would pass block 127"
    missing = dev.seed_many([(first + i, b) for i, b in enumerate(blocks)])
    if missing:
        results.append((f"{name}: upload", False, f"no ack for {missing}")); return None
    for i in range(len(blocks)):
        rep = dev.cmd(f"{first + i} LOAD", timeout=25.0, allow_error=True)
        errs = [l.strip() for l in rep.splitlines() if l.strip().endswith("?") or "ERR_" in l]
        if errs:
            results.append((f"{name}: compile", False, f"block {first + i}: {errs[0]}")); return None
    results.append((f"{name}: compile", True, f"{len(blocks)} blocks"))
    return blocks


def main():
    results = []
    dev = Dev(PORT)
    try:
        fresh = False
        for attempt in range(4):
            # GUARDRAIL: a "reset" that did not happen silently poisons the run - the still-running launcher answers
            # politely and the test compiles a second copy into a full dictionary. Prove freshness.
            dev.pulse_reset(1.0) if attempt < 2 else dev.reset(settle=1.2)
            try:
                here = dev.num("HERE .", timeout=5.0)
                free = dev.num("LATEST HERE - .", timeout=5.0)
            except Exception:
                continue
            if here < 900 and free > 700:
                fresh = True; break
        results.append(("fresh boot", fresh, f"here={here} free={free}"))
        if not fresh:
            raise SystemExit(report(results))

        dev.cmd("0 2 BLKXFER", timeout=6.0, allow_error=True)
        if not compile_file(dev, EX / "menu.fs", MENU_FIRST, "launcher", results):
            raise SystemExit(report(results))
        dev.cmd("SEAL")
        base = dev.num("bh @ .")
        results.append(("seal resident launcher", base > 786, f"base={base} HERE={dev.num('HERE .')}"))

        for path, desc, entry in ((EX / "demo_bars.fs", BARS_DESC, "RUNB"),
                                  (EX / "demo_spin.fs", SPIN_DESC, "RUNS")):
            # GUARDRAIL: rewind to the seal BEFORE every build. Without the rewind each demo is compiled ON TOP of the
            # previous one, the image spans both, and adopting it runs whatever happened to be last.
            dev.cmd("2 OVL")
            if not compile_file(dev, path, DEMO_FIRST, path.name, results):
                raise SystemExit(report(results))
            cs = dev.num("bh @ .")
            ce = dev.num("HERE .")
            # GUARDRAIL: a stub image is the signature of a failed LOAD (measured: 135 B instead of 576, and EXECUTE
            # then jumps into never-compiled bytes and spins). Refuse by name instead of adopting it.
            # GUARDRAIL: 120 B was the phase threshold and it wrongly rejected a legitimate 92 B, 2-block demo. The
            # stub that actually hung the machine was 10 B, so the checks that matter are: the code starts AT the seal
            # (not above it) and the entry point lands INSIDE the code it is supposed to run.
            hs, he = dev.num("LATEST ."), dev.num("bl @ .")
            ent = dev.num(f"' {entry} .")
            if cs != base or ce - cs < 48 or not (cs <= ent < ce):
                results.append((f"{path.name}: size", False,
                                f"code {cs}..{ce} ({ce - cs} B) entry {ent}: expected code at seal {base} with entry inside"))
                raise SystemExit(report(results))
            dev.cmd(f"#d {desc} {cs} {ce} {hs} {he} {ent}", timeout=20.0)
            results.append((f"{path.name}: image", True, f"{ce - cs} B of code -> blocks {desc}..{desc + 4}, entry {ent}"))

        dev.cmd("2 OVL")
        os.write(dev.fd, b"RUNP\r"); time.sleep(0.35)
        os.write(dev.fd, b"!RAW\r"); time.sleep(0.25)
        menu = read_frame(dev)
        results.append(("menu frame", b"PROGRAM LIBRARY" in menu and clean(menu), show(menu)))

        t0 = time.time()
        os.write(dev.fd, b"\r")
        b1 = read_frame(dev)
        t1 = time.time() - t0
        results.append(("Enter -> colour bars", b"BARS" in b1 and clean(b1), f"{t1 * 1000:.0f} ms, {show(b1, 60)}"))

        os.write(dev.fd, b"q")
        m2 = read_until(dev, b"PROGRAM LIBRARY")
        results.append(("q -> back to the launcher", b"PROGRAM LIBRARY" in m2 and clean(m2), show(m2, 60)))

        os.write(dev.fd, b"k")          # two entries: toggle to the other one
        m3 = read_until(dev, b"PROGRAM LIBRARY")
        t0 = time.time()
        os.write(dev.fd, b"\r")
        s1 = read_until(dev, b"SPIN")
        t2 = time.time() - t0
        results.append(("Enter -> spinner", b"SPIN" in s1 and clean(s1), f"{t2 * 1000:.0f} ms, {show(s1, 60)}"))
        results.append(("k moved the marker", b"PROGRAM LIBRARY" in m3 and clean(m3), show(m3, 40)))

        os.write(dev.fd, b"q")
        m4 = read_until(dev, b"PROGRAM LIBRARY")
        results.append(("q -> launcher again", b"PROGRAM LIBRARY" in m4 and clean(m4), show(m4, 60)))

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
