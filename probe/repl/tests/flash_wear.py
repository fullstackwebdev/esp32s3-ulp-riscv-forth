#!/usr/bin/env python3
"""flash_wear.py — STEP 6 item 1-3: erases per phase switch and per SAVE, and the sector lifetime that follows.

`dry` (no chip): parse the `#i` counter line from known strings, so the measurement cannot be misread.
`run` (one chip session): 15 phases (build+adopt) then 200 data-block SAVEs, reporting per-sector erases.
"""
import sys, re, pathlib
sys.path.insert(0, "tools")
from devio import Dev
sys.path.insert(0, "tests")
from step4 import phase_src, build_and_adopt, IMG_AREA, DATA, PAT

ENDURANCE = 100000          # NOR flash program/erase cycles per sector (datasheet order of magnitude)
wd = pathlib.Path(".auto/tmp")


def parse(info):
    m = re.search(r"erases/sector((?: \d+:\d+)+)", info)
    if not m:
        return None
    pairs = [p.split(":") for p in m.group(1).split()]
    per = {int(a): int(b) for a, b in pairs}
    hot = max(per.items(), key=lambda kv: kv[1])
    return per, hot


def dry():
    sample = "info: store ok, 160 blocks x 128 B | programmed 4144 B, 9 erase(s), 3 flush(es)\ninfo: erases/sector 0:2 1:5 2:1 3:0 4:0 5:0 | hottest sector 1 (5)"
    got = parse(sample)
    ok = got is not None and got[1] == (1, 5) and got[0][2] == 1
    print(f"  parsed: {got}")
    print(f"  parser: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def run():
    with Dev() as d:
        d.cmd("#x")
        # GUARDRAIL: define W first. build_and_adopt() checks the adopted entry through `W @ .`, so without it every cycle
        # fails on `W?` - "no number in reply to 'W @ .'" - which reads like a loader fault and was my omission twice.
        d.cmd("0 BLOCK CONSTANT W")
        base = parse(d.cmd("#i"))[0]
        for p in range(1, 16):
            build_and_adopt(d, p, IMG_AREA + (p - 1) * 5, phase_src(p))
        d.cmd("#f")
        after_phases = parse(d.cmd("#i"))[0]
        # 200 data-block SAVEs: the Forth path that actually writes a block
        d.cmd("0 BLOCK CONSTANT W")
        d.cmd(f": BUMP 1 {DATA(1)} BLOCK C! {DATA(1)} BLOCK DROP UPDATE SAVE DROP ;", timeout=10.0)
        for _ in range(200):
            d.cmd("BUMP", timeout=10.0)
        d.cmd("#f")
        info = d.cmd("#i")
        after_saves = parse(info)[0]
        hot = parse(info)[1]
    delta_ph = {k: after_phases[k] - base[k] for k in base}
    delta_sv = {k: after_saves[k] - after_phases[k] for k in base}
    print(f"  erases from 15 phases (images, 75 blocks): {sum(delta_ph.values())}  per phase = {sum(delta_ph.values())/15:.2f}")
    print(f"  erases from 200 SAVEs of ONE block      : {sum(delta_sv.values())}  per SAVE  = {sum(delta_sv.values())/200:.3f}")
    print(f"  hottest sector overall: {hot[0]} with {hot[1]} erase(s)")
    tot = sum(after_saves.values()) or 1
    for label, switches_per_day in (("1 switch/min", 60 * 24), ("1/s", 86400)):
        days = ENDURANCE / (tot / switches_per_day) / 1 if switches_per_day else 0
        print(f"  lifetime at {label}: {ENDURANCE/(tot/max(switches_per_day,1)):.0f} days "
              f"(total erases {tot}, endurance {ENDURANCE})")
    return 0


if __name__ == "__main__":
    sys.exit({"dry": dry, "run": run}[sys.argv[1]]() or 0)
