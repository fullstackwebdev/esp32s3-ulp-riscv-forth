#!/usr/bin/env python3
"""Does an image cycle still work after an error rewound the dictionary? STEP: last open question.

Sequence: error -> inspect machine state -> dump+adopt -> inspect -> execute. Every step prints `#u` fields so a hang
names where it happened instead of just going silent.
"""
import sys
sys.path.insert(0, "tools"); sys.path.insert(0, "tests")
from devio import Dev
from step4 import build_and_adopt, phase_src, IMG_AREA


def state(d):
    r = d.cmd("#u", timeout=8.0)
    keep = {}
    for ln in r.splitlines():
        s = ln.strip()
        if "ulp vars:" in s or "ulp blk_out" in s or "hp view:" in s:
            keep[s.split(":")[0] + ":" + s.split(":", 1)[1][:95]] = 1
    return list(keep)


def show(d, tag):
    for s in state(d):
        print(f"    {tag} {s}")


with Dev() as d:
    print("  --- clean baseline")
    d.cmd("0 BLOCK CONSTANT W")
    show(d, "ok ")
    print("  --- raise an error (undefined word): rewinds the dictionary")
    print(f"    reply: {d.cmd('NOPE', timeout=8.0, allow_error=True).strip()[:60]!r}")
    show(d, "err")
    print(f"    HERE={d.num('HERE .')} LATEST={d.num('LATEST .')} (a rewind puts both back to the baked values)")
    print("  --- now the image cycle")
    ok, cells, note = build_and_adopt(d, 1, IMG_AREA, phase_src(1), execute=False)
    print(f"    adopted={ok} note={note}")
    d.cmd("W @ EXECUTE", timeout=20.0)
    print(f"    executed cells={[d.num(f'z{i} @ .') for i in range(1, 7)]}")
