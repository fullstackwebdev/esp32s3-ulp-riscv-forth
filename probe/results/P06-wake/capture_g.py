#!/usr/bin/env python3
"""P06 wake-semantics capture: wait for READY on UART0, send 'g', log everything.

pyserial rather than picocom so the whole run lands in a file and the 'g' gate is
deterministic.  DTR/RTS are dropped immediately after open: on the CH343 they drive
EN/IO0, so a default-asserted open would reboot the chip and lose the banner stage.
"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM1"
OUT = sys.argv[2] if len(sys.argv) > 2 else "run_v2.log"
WAIT_READY_S = 6.0
TOTAL_S = 20.0

t_open = time.time()
ser = serial.Serial()
ser.port = PORT
ser.baudrate = 115200
ser.timeout = 0.05
ser.dtr = False
ser.rts = False
ser.open()
ser.dtr = False
ser.rts = False

sent = False
boot_at = None
lines = []
with open(OUT, "w") as f:
    while time.time() - t_open < TOTAL_S:
        chunk = ser.read(256)
        if not chunk:
            if (not sent) and time.time() - t_open > 0.5:
                # unsolicited: give the app a moment even if the banner was missed
                pass
            continue
        text = chunk.decode("utf-8", "replace")
        f.write(text)
        f.flush()
        lines.append(text)
        if boot_at is None:
            boot_at = time.time()
        if (not sent) and "READY" in "".join(lines):
            time.sleep(0.05)
            ser.write(b"g")
            ser.flush()
            sent = True
            f.write("\n[capture] sent 'g' at t+%.2fs\n" % (time.time() - t_open))
            f.flush()
        if "P06 done" in "".join(lines):
            break
    f.write("\n[capture] end t+%.2fs sent_g=%s bytes=%d\n"
            % (time.time() - t_open, sent, sum(len(x) for x in lines)))
ser.close()
print("capture done sent_g=%s total_bytes=%d" % (sent, sum(len(x) for x in lines)))
