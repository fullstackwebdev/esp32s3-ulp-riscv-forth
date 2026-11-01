#!/usr/bin/env python3
"""Host-only check of the preflight verdict, using REAL device transcripts.

Two earlier versions passed here and failed on the board: "the last line is numeric" (a transcript ends with `ok`) and "a
line consisting only of digits" (the device prints `52 ok` on one line). Fixtures are now copied verbatim from the device.
"""
import re

def verdict(reply):
    lines = [s.strip() for s in reply.splitlines() if s.strip()]
    return any(re.search(r"-?\d", s) for s in lines) and not any(s.endswith("?") for s in lines)

cases = [
    ("' HERE .\n52 ok\n", True),      # verbatim from /dev/ttyACM1
    ("' ZZ .\nZZ?\n", False),        # verbatim
    ("' W .\n1808 ok\n", True),
    ("ok\n", False),
    ("' HERE .\n52 ok\n10 DUP .\n", True),
]
ok = all(verdict(r) == want for r, want in cases)
for r, want in cases:
    print(f"  {r.replace(chr(10), ' ')!r:30s} -> {verdict(r)} (want {want})")
print(f"  preflight logic: {'PASS' if ok else 'FAIL'}")
raise SystemExit(0 if ok else 1)
