#!/usr/bin/env python3
"""Capture the 104-word register dump from whichever firmware is flashed.

GUARDRAIL: read for a fixed wall-clock window, not until a marker - the dump is 104 lines of printf and the console has
no completion token, so a short read silently returns a partial list, which reads like a register difference (160 of 192
captured on the first run looked like 32 mismatched registers rather than 32 missing lines).
"""
import re, sys, serial, time
port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
mode = "cmd" if len(sys.argv) <= 2 else sys.argv[2]
s = serial.Serial(port, 115200, timeout=0.4)
s.setDTR(False); s.setRTS(True); time.sleep(0.2); s.setRTS(False)
time.sleep(1.2); s.reset_input_buffer()
if mode == "cmd":
    s.write(b"#d\r\n")
buf, t0 = "", time.time()
while time.time() - t0 < 30:
    c = s.read(8192)
    if c: buf += c.decode("latin-1", "replace")
s.close()
out = ["%s = %s" % (a, v) for a, v in re.findall(r"REG (0x[0-9A-F]{8}) = (0x[0-9A-F]{8})", buf)]
print("\n".join(out))
sys.stderr.write("captured %d registers\n" % len(out))
