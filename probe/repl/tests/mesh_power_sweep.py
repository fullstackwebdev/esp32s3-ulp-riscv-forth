#!/usr/bin/env python3
"""Find the transmit power that the stock node actually decodes, 20 frames per level.

    python3 tests/mesh_power_sweep.py --ours /dev/ttyUSB0 --peer /dev/ttyUSB1

Two boards centimetres apart fight each other: at high power each receiver's front end is desensed, at minimum power the
signal is under the local noise. This sweeps the middle and counts real decodes (live-read log), so the answer is a
measurement rather than a preference.

GUARDRAIL: attribute events by time window while reading the stream live - a log read at the end cannot tell which power
level produced which decode.
"""
import argparse
import pathlib
import re
import subprocess
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
from devio import Dev                      # noqa: E402
from lora_frame_phase import load          # noqa: E402

BASE = REPO / "examples/apps/lora/loratx_ms_low.fs"   # 869.480 MHz - the carrier both radios actually use
CLR = "NSSLO 2 >BYTE 255 >BYTE 255 >BYTE NSSHI"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", default="/dev/ttyUSB0")
    ap.add_argument("--peer", default="/dev/ttyUSB1")
    ap.add_argument("--powers", default="-9,0,7,14")
    ap.add_argument("--frames", type=int, default=20)
    a = ap.parse_args()

    events = []
    lock = threading.Lock()
    listener = subprocess.Popen(["meshtastic", "--port", a.peer, "--listen", "--debug"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    def reader():
        for line in listener.stdout:
            with lock:
                if "hi from ulp" in line:
                    events.append((time.monotonic(), "DECODE"))
                elif "Ignore false preamble detection" in line:
                    events.append((time.monotonic(), "pre"))
    threading.Thread(target=reader, daemon=True).start()
    time.sleep(18)

    src = BASE.read_text()
    for power in [int(x) for x in a.powers.split(",")]:
        byte = power & 0xFF                                    # SetTxParams power is a SIGNED byte
        t = re.sub(r"  3 C, 142 C, \d+ C, 4 C,", f"  3 C, 142 C, {byte} C, 4 C,", src, count=1)
        f = REPO / f"examples/apps/lora/loratx_ms_pw{power}.fs"
        f.write_text(t)
        dev = Dev(port=a.ours); dev.reset(); time.sleep(2)
        load(dev, f)
        dev.num("RADIO-INIT .", 40.0)
        t0, sent = time.monotonic(), 0
        for _ in range(a.frames):
            dev.cmd(CLR, 10.0, allow_error=True); dev.num("GO .", 90.0); sent += 1
            time.sleep(0.7)
        t1 = time.monotonic()
        with lock:
            dec = sum(1 for t_, k in events if k == "DECODE" and t0 <= t_ <= t1)
            pre = sum(1 for t_, k in events if k == "pre" and t0 <= t_ <= t1)
        print(f"  power {power:+3d} dBm: {sent} frames -> decodes {dec}, preamble events {pre}", flush=True)
        dev.close()
    listener.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
