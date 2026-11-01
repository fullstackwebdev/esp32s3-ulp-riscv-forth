#!/usr/bin/env python3
"""step4c.py — STEP 4c. `loop` is the 15-cycle source-only loop (item 1/2); `probe` answers whether the data stack
survives between LINES, which decides whether item 3's "drain with . until underflow" can measure anything at all."""
import sys, re, pathlib
sys.path.insert(0, "tools")
from devio import Dev
sys.path.insert(0, "tests")
from step4 import phase_src, DATA, PAT, HOST_PREFIXES

wd = pathlib.Path(".auto/tmp")


def probe():
    """Does the data stack survive from one line to the next?"""
    with Dev() as d:
        d.cmd("1 2 3")
        a = d.cmd(".", timeout=8.0)
        b = d.cmd(".", timeout=8.0)
        c = d.cmd(".", timeout=8.0)
        print(f"  after `1 2 3`: '.' -> {a.strip()[:40]!r} then {b.strip()[:40]!r} then {c.strip()[:40]!r}")
        persists = any(str(x) in a + b + c for x in (3, 2, 1)) and "ERR_STACK" not in a
        print(f"  stack survives between lines: {persists}")


def loop(with_reset=False):
    """15 cycles of SOURCE load only (no dump, no adopt). Logs HERE and LATEST after every cycle.

    GUARDRAIL: HERE/LATEST are read on their own lines, which is safe because they are pushed and printed within one
    line (`HERE .`). The point of logging them is that a leak in the overlay bookkeeping shows as a DRIFT here, one cycle
    before it becomes an ERR_STACK.
    """
    with Dev() as d:
        d.cmd("0 BLOCK CONSTANT W")
        d.cmd("SEAL")
        here0 = d.num("bh @ .")
        print(f"  sealed HERE {here0}")
        for p in range(1, 16):
            blocks = phase_src(p)
            miss = d.seed_many([(2, " " * 128), (DATA(p), PAT(p))] + [(8 + k, b) for k, b in enumerate(blocks)])
            if miss:
                print(f"  cycle {p}: SEED FAILED {miss}"); return 1
            d.cmd("2 OVL")
            for k in range(len(blocks)):
                out = d.cmd(f"{8+k} LOAD", timeout=10.0)
                if "?" in out.replace("LOAD", "").replace(str(8 + k), ""):
                    print(f"  cycle {p}: FAILED on {8+k} LOAD -> {' '.join(out.split())}"); return 1
            d.cmd("RUNPH1", timeout=15.0)
            here = d.num("HERE ."); lat = d.num("LATEST .")
            if with_reset:
                d.cmd("0 2 BLKXFER"); d.cmd("2 OVL")
            here2 = d.num("HERE ."); lat2 = d.num("LATEST .")
            print(f"  cycle {p:2d}: HERE {here} (+{here-here0}) LATEST {lat} | after rewind HERE {here2} LATEST {lat2}")
        print(f"  loop completed 15 cycles (reset={with_reset})")
    return 0


def depth(after_cycles):
    """Run cycles 1..N WITH dump/adopt, then drain the data stack and report how many values were left over.

    GUARDRAIL: this is only meaningful because the stack SURVIVES between lines on this machine - measured here as
    `1 2 3` then `.` answering 3, 2, 1. An earlier conclusion of "no persistence" (from `40 3 BLKXFER` then `.` answering
    ERR_STACK) was wrong: BLKXFER's status had already been consumed by the caller in that test.
    """
    with Dev() as d:
        d.cmd("0 BLOCK CONSTANT W")
        for p in range(1, after_cycles + 1):
            from step4 import build_and_adopt, IMG_AREA
            ok, got, note = build_and_adopt(d, p, IMG_AREA + (p - 1) * 5, phase_src(p))
            if not ok:
                print(f"  cycle {p}: build/adopt FAILED {note}")
        out = d.cmd(". . . . . . . . . . . . . . . . . . . .", timeout=15.0)
        nums = [x for x in Dev.nums(out) if x not in (0,)]
        left = [n for n in Dev.nums(out)]
        print(f"  after cycle {after_cycles}: drained {len(left)} value(s) {left[:12]} "
              f"{'then ERR_STACK' if 'ERR_STACK' in out else '(more may remain)'}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "probe":
        sys.exit(probe() or 0)
    if cmd in ("noreset", "reset"):
        sys.exit(loop(cmd == "reset") or 0)
    sys.exit(depth(int(cmd)) or 0)
