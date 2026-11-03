#!/usr/bin/env python3
"""Sweep OUR transmit carrier finely and count real decodes by the stock node.

    python3 tests/mesh_tx_freq_sweep.py --ours /dev/ttyUSB1 --peer /dev/ttyUSB0

Why: our receiver reports a systematic -45.7 kHz error on every packet the peer sends (GetPacketStatus FEI), which means
our radio's nominal is 45.7 kHz above theirs. Our transmitter uses the same nominal, so every frame we sent landed ~46 kHz
off their receive centre - far enough that the preamble still correlates but the header fails. This searches for the
carrier where the peer actually decodes us, instead of assuming 869.480 is right.

GUARDRAIL: count DECODE events live and attribute them by time window. A log read at the end cannot say which frequency
produced what, and "preamble detected" is NOT success - only a decoded packet is.
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

BASE = REPO / "examples/apps/lora/loratx_ms_final.fs"
CLR = "NSSLO 2 >BYTE 255 >BYTE 255 >BYTE NSSHI"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", default="/dev/ttyUSB1")
    ap.add_argument("--peer", default="/dev/ttyUSB0")
    ap.add_argument("--from-mhz", dest="f0", type=float, default=869.400)
    ap.add_argument("--to-mhz", dest="f1", type=float, default=869.480)
    ap.add_argument("--step-khz", type=float, default=5.0)
    ap.add_argument("--frames", type=int, default=3)
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
    dev = None
    f = a.f0
    best = (0, None)
    while f <= a.f1 + 1e-9:
        mhz = round(f, 3)
        w = round(mhz * 1e6 * 2 ** 25 / 32e6)
        out = re.sub(r"  5 C, 134 C, \d+ C, \d+ C, \d+ C, \d+ C,",
                     f"  5 C, 134 C, {(w >> 24) & 255} C, {(w >> 16) & 255} C, {(w >> 8) & 255} C, {w & 255} C,",
                     src, count=1)
        fp = REPO / f"examples/apps/lora/loratx_ms_fs{mhz}.fs"
        fp.write_text(out)
        if dev is not None:
            dev.close()
        dev = Dev(port=a.ours); dev.reset(); time.sleep(1.5)
        load(dev, fp)
        dev.num("RADIO-INIT .", 40.0)
        t0 = time.monotonic()
        for _ in range(a.frames):
            dev.cmd(CLR, 10.0, allow_error=True); dev.num("GO .", 90.0); time.sleep(0.9)
        t1 = time.monotonic()
        with lock:
            dec = sum(1 for t, k in events if k == "DECODE" and t0 <= t <= t1)
            pre = sum(1 for t, k in events if k == "pre" and t0 <= t <= t1)
        print(f"  {mhz:.3f} MHz -> decodes {dec}, preamble {pre}", flush=True)
        if dec > best[0]:
            best = (dec, mhz)
        f += a.step_khz / 1000.0
    listener.kill()
    if dev:
        dev.close()
    print(f"  BEST: {best[0]} decode(s) at {best[1]} MHz")
    return 0


if __name__ == "__main__":
    sys.exit(main())
