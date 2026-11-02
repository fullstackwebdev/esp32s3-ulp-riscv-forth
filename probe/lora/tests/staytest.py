#!/usr/bin/env python3
"""Decide whether the ULP's C store to RTCIO lands, from the stay-awake transcript.

GUARDRAIL: key the reading to the EVENT, not to a poll interval. The ULP wakes every ~5 s; a 1 s poll reported LOST for a
store that landed at the next wake, and earlier reported LANDED because a stale level happened to still be set. The
transcript now prints one line per ULP wake, and the HP core clears bit 18 at t+1, so the first AWAKETEST after that clear
is the only sample that means anything.
"""
import re, sys, serial, time

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
s = serial.Serial(port, 115200, timeout=0.4)
s.setDTR(False); s.setRTS(True); time.sleep(0.2); s.setRTS(False)
t0, buf = time.time(), ""
while time.time() - t0 < 26:
    buf += s.read(4096).decode("latin-1", "replace")
s.close()
samples = [(int(m.group(1)), int(m.group(2), 16)) for m in
           re.finditer(r"AWAKETEST runs=(\d+) OUT=0x([0-9A-F]{8})", buf)]
if not samples:
    print("NO AWAKETEST LINES - the build did not run or the ULP never woke"); raise SystemExit(2)
for r, v in samples:
    print("  wake %-3d OUT 0x%08X bit18 %s" % (r, v, "SET" if v & (1 << 18) else "clear"))
good = [v for _, v in samples[1:]]      # the first wake precedes the HP core's clear
landed = bool(good) and all(v & (1 << 18) for v in good)
print("VERDICT: ULP store %s (%d wakes after the HP clear)" %
      ("LANDED" if landed else "LOST", len(good)))
raise SystemExit(0 if landed else 1)
