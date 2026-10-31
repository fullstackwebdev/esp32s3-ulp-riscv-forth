#!/usr/bin/env python3
"""P39 capture: wait for READY on UART0, send 'g', log every byte to a file.

pyserial rather than picocom so the whole run lands in a file and the 'g' gate is deterministic.
GUARDRAIL: DTR/RTS are dropped immediately after open — on this CH343 they drive EN/IO0, so a
default-asserted open reboots the chip and the banner stage is lost (P06 lost a run to exactly that).
"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM1"
OUT = sys.argv[2] if len(sys.argv) > 2 else "logs/run.log"
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
buf = []
nbytes = 0
with open(OUT, "w") as f:
    while time.time() - t_open < TOTAL_S:
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
            f.write("\n[capture] sent 'g' at t+%.2fs\n" % (time.time() - t_open))
            f.flush()
        if "P39 done" in joined:
            break
    f.write("\n[capture] end t+%.2fs sent_g=%s bytes=%d\n" % (time.time() - t_open, sent, nbytes))
ser.close()
print("capture done sent_g=%s total_bytes=%d" % (sent, nbytes))
