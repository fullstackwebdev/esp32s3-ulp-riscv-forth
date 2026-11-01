#!/usr/bin/env python3
"""hang_probe.py — STEP 6c: is the hang the HP core, the ULP, or a never-returning flash call?

One session, no patch-and-retry. Order: reproduce once, ask the HP core while it hangs (`#i`), ask the ULP while it hangs
(`2 3 + .`), then reboot and read the breadcrumb, the flash durations and the reset reason.
"""
import sys, os, time, select
sys.path.insert(0, "tools")
from devio import Dev
sys.path.insert(0, "tests")
from step4 import phase_src, build_and_adopt, IMG_AREA, DATA

WORDS = ["HERE", "LATEST", "W", "BLOCK", "CONSTANT", "OVL", "SEAL", "BLKXFER", "DROP", "EXECUTE", "@", "."]


def talk(fd, line, wait=0.6):
    os.write(fd, line.encode() + b"\r")
    buf, end = b"", time.time() + wait
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.02)
        if r:
            try: buf += os.read(fd, 4096)
            except BlockingIOError: pass
    return buf.decode(errors="replace")


def attempt(d, p):
    """Build phase p, fire the execute WITHOUT waiting, then ask both halves while it may be stuck."""
    ok, _, note = build_and_adopt(d, p, IMG_AREA + (p - 1) * 5, phase_src(p), execute=False)
    before = [l for l in d.cmd("#i").splitlines() if "bc " in l]
    os.write(d.fd, b"W @ EXECUTE\r")
    time.sleep(0.4)
    hp1 = talk(d.fd, "#i", 1.2)
    ulp = talk(d.fd, "2 3 + .", 1.2)
    time.sleep(1.0)
    hp2 = talk(d.fd, "", 0.3)
    done = "ok" in (hp2 + ulp)
    print(f"  p{p}: build={ok} bc_before={before[-1][8:20] if before else '-'} "
          f"HP={'YES' if 'info:' in hp1 else 'NO'} ULP={'YES' if '5 ok' in ulp else 'NO'} "
          f"execute_finished={'YES' if done else 'NO'}")
    return not done


def run():
    with Dev() as d:
        d.cmd("#x")
        # GUARDRAIL: define harness-created words BEFORE preflight. `W` is made by this script, not resident in the
        # dictionary, so preflighting first reports it missing and looks like a firmware fault.
        d.cmd("0 BLOCK CONSTANT W")
        d.preflight(WORDS)
        print("  preflight: every word the harness uses exists")
        # six chances to catch the intermittent hang; each is one build + one raw execute
        hung = [p for p in range(1, 7) if attempt(d, p)]
        print(f"  hangs seen at phases: {hung if hung else 'none in 6 attempts'}")
        if hung:
            r = d.cmd("#i", timeout=6.0)
            print(f"  during hang: {[l.strip() for l in r.splitlines() if 'bc ' in l][-1:] or '(HP did not answer)'}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
