#!/usr/bin/env python3
"""sb_range_check.py — the suite's block range must not overlap the test fixtures or the phase ranges.

GUARDRAIL: a resident overlap check would cost application bytes for a condition that can only change when someone edits
SB. Checking the source is just as loud (it fails the build's test run), costs nothing, and cannot drift from the value
that is actually baked.
"""
import pathlib, re, sys

FIXTURES = {5: "silent block (no-answer path)", 7: "bad-checksum block"}
PHASE_RANGES = [(8, 127)]

src = pathlib.Path("src/p39b_overlay.fs").read_text()
m = re.search(r"^(\d+) CONSTANT SB\b", src, re.M)
if not m:
    print("FAIL  SB is not defined in src/p39b_overlay.fs"); sys.exit(1)
sb = int(m.group(1))
print(f"  SB = {sb}")
bad = []
# GUARDRAIL: the tests must not repeat the number. Read the one place they use it and require agreement, or a menu and a
# tool end up writing different blocks while both claiming to use "the suite block".
mt = pathlib.Path("tests/menu_tool.py").read_text()
import re as _re
dm = _re.search(r"DATA_BLK\s*=\s*(\d+)", mt)
if not dm:
    bad.append("tests/menu_tool.py has no DATA_BLK to cross-check")
elif int(dm.group(1)) != sb:
    bad.append(f"tests/menu_tool.py DATA_BLK={dm.group(1)} disagrees with SB={sb}")
if sb in FIXTURES:
    bad.append(f"SB {sb} is a fixture block: {FIXTURES[sb]}")
for lo, hi in PHASE_RANGES:
    if lo <= sb <= hi:
        bad.append(f"SB {sb} lies inside the test phase range {lo}..{hi}")
for b, why in FIXTURES.items():
    if b == sb:
        bad.append(why)
if bad:
    print("FAIL  " + "; ".join(bad)); sys.exit(1)
print(f"PASS  SB={sb} is clear of fixtures {sorted(FIXTURES)} and phase ranges {PHASE_RANGES}")
