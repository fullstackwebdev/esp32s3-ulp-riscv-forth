#!/usr/bin/env python3
"""P39 capture with a real reset: pulse the CH343's reset line, then wait for READY, then send 'g'.

The first capture saw zero bytes because esptool's `Hard resetting via RTS pin` leaves the app
starting just as the flasher closes the port, and a plain open does not reset anything.
GUARDRAIL: the reset here is RTS (EN on this CH343), and IO0 is left released (DTR false) — asserting
both at once is what puts the chip in download mode, where the app never runs and the log stays empty.
"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM1"
OUT = sys.argv[2] if len(sys.argv) > 2 else "logs/run.log"
TOTAL_S = 20.0

ser = serial.Serial()
ser.port = PORT
ser.baudrate = 115200
ser.timeout = 0.05
ser.dtr = False
ser.rts = False
ser.open()
# reset: RTS asserted (EN low), IO0 (DTR) released so the ROM boots the app, not the downloader
ser.dtr = False
ser.rts = True
time.sleep(0.15)
ser.rts = False
time.sleep(0.05)

t0 = time.time()          # the window starts at the reset, so the banner cannot be missed
sent = False
buf = []
nbytes = 0
with open(OUT, "w") as f:
    while time.time() - t0 < TOTAL_S:
        chunk = ser.read(512)
        if not chunk:
            continue
        text = chunk.decode("utf-8", "replace")
        f.write(text)
        f.flush()
        nbytes += len(chunk)
        buf.append(text)
        joined = "".join(buf)
        if (not sent) and "READY" in joined:
            time.sleep(0.05)
            ser.write(b"g")
            ser.flush()
            sent = True
            f.write("\n[capture] sent 'g' at t+%.2fs\n" % (time.time() - t0))
            f.flush()
        if "P39 done" in joined:
            break
    f.write("\n[capture] end t+%.2fs sent_g=%s bytes=%d\n" % (time.time() - t0, sent, nbytes))
ser.close()
print("capture done sent_g=%s total_bytes=%d" % (sent, nbytes))
