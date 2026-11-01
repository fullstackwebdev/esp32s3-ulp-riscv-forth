#!/usr/bin/env python3
"""wedge_probe.py — STEP 6c-ii: is the wedge cleared by reset, what does the boot log say, and which flash call died?

One session. Order: (1) is the board talking at all, (2) hard reset while holding the port and keep the ROM log,
(3) the app's own reset reason and the RTC breadcrumb from before that reset, (4) reproduce the hang and read what
survives it.
"""
import sys, os, time
sys.path.insert(0, "tools")
from devio import Dev
sys.path.insert(0, "tests")
from step4 import phase_src, build_and_adopt, IMG_AREA


def show(tag, txt, keys=("rst:0x", "boot:", "Guru", "abort", "panic", "Backtrace", "store:", "REFUSED", "info: bc")):
    hits = [l.strip() for l in txt.splitlines() if any(k in l for k in keys)]
    print(f"  {tag}: " + (" | ".join(hits[:6]) if hits else f"(no key lines; {len(txt)} B of output)"))


def run():
    d = Dev()
    d.reset(settle=1.0)
    alive = d.cmd("#i", timeout=5.0) if True else ""
    print(f"  board talking before reset: {'YES' if 'info:' in alive else 'NO'}")

    boot = d.hard_reset_capture(4.0)
    show("boot log", boot)
    loops = boot.count("boot:")
    print(f"  boot-loop lines: {loops}")

    d.drain(0.6)
    r = d.cmd("#i", timeout=8.0)
    line = [l.strip() for l in r.splitlines() if "bc " in l]
    print(f"  #i after reset: {line[-1] if line else '(HP did not answer)'}")

    d.cmd("#x")
    d.cmd("0 BLOCK CONSTANT W")
    for p in range(1, 5):
        ok, _, _ = build_and_adopt(d, p, IMG_AREA + (p - 1) * 5, phase_src(p), execute=False)
        os.write(d.fd, b"W @ EXECUTE\r")
        time.sleep(1.2)
        probe = d.cmd("#i", timeout=6.0)
        ulp_state = d.cmd("#u", timeout=6.0)
        if "info:" in probe:
            print(f"  p{p}: execute ok, {[l.strip()[5:] for l in probe.splitlines() if 'bc ' in l][-1:]}")
            print(f"  p{p}: {[l.strip() for l in ulp_state.splitlines() if 'ulp ' in l][-1:]}")
            a = d.cmd("1 1 + .", timeout=6.0) if True else ""
            b = d.cmd("HERE .", timeout=6.0)
            print(f"  p{p}: ULP words after execute: {'ok' if '2 ok' in a and 'ok' in b else 'STALLED'}")
        else:
            print(f"  p{p}: HP DID NOT ANSWER -> wedged")
            boot2 = d.hard_reset_capture(4.0)
            show("boot after wedge", boot2)
            d.drain(0.6)
            r2 = d.cmd("#i", timeout=8.0)
            l2 = [l.strip() for l in r2.splitlines() if "bc " in l]
            print(f"  RTC breadcrumb survived the wedge: {l2[-1] if l2 else '(no answer)'}")
            break
    d.close()
    return 0


if __name__ == "__main__":
    sys.exit(run())
