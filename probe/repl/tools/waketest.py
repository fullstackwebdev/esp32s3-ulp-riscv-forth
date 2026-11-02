#!/usr/bin/env python3
"""Decide whether THIS firmware's ULP store to RTCIO lands, keyed to the wake counter.

GUARDRAIL: sample on the EVENT (#u's `wakes`), never on a wall-clock poll. Two earlier verdicts in this investigation were
wrong for exactly that reason, in both directions (docs/14 R20). The HP core clears pad 8's bit first; when it is SET
again after at least one reported wake, the ULP's store landed, and nothing else can have set it.
"""
import re, sys, time, serial

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
s = serial.Serial(port, 115200, timeout=0.4)
s.write(b"\r\n"); time.sleep(0.6); s.reset_input_buffer()

def cmd(line, wait=1.2):
    s.write(line.encode() + b"\r\n"); time.sleep(wait)
    return s.read(1400).decode("latin-1", "replace")

def wakes(rep):
    m = re.search(r"wakes (\d+)", rep)
    return int(m.group(1)) if m else None

def out():
    rep = cmd("#g")
    m = re.search(r"gpio: OUT 0x([0-9A-F]{8})", rep)
    return int(m.group(1), 16) if m else None

# GUARDRAIL: pad 11 (bit 21), which nothing on the HP side idles high. Pad 8 is NSS and starts SET, so a probe on it decides
# nothing until the HP core clears it - that extra step is the R18 baseline trap in its natural habitat.
w0, o0 = wakes(cmd("#u")), out()
print("start: wakes %s OUT 0x%08X bit21 %s" % (w0, o0, "SET" if o0 & (1 << 21) else "clear"))
w1, o1 = wakes(cmd("#u", 1.5)), out()
print("later: wakes %s OUT 0x%08X bit21 %s" % (w1, o1, "SET" if o1 & (1 << 21) else "clear"))
s.close()
if w0 is None or w1 is None or o0 is None or o1 is None:
    print("NO TRANSCRIPT"); raise SystemExit(2)
ran = (w1 or 0) > (w0 or 0)
landed = bool(o1 & (1 << 21))
print("VERDICT: ULP woke=%s store=%s" % (ran, "LANDED" if landed else "LOST"))
raise SystemExit(0 if (ran and landed) else 1)
