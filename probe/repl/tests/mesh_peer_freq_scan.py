#!/usr/bin/env python3
"""Find the frequency the stock node's RECEIVER is listening on, by giving it an unmissable preamble.

    python3 tests/mesh_peer_freq_scan.py --ours /dev/ttyUSB0 --peer /dev/ttyUSB1 [--from 869.34] [--to 869.54]

Method: transmit one frame carrying a 512-symbol preamble (~4.2 s at SF11/BW250 - far longer than any duty-cycle window)
at each candidate carrier, and count the peer's own `Ignore false preamble detection` records in a live-read window.
A receiver listening on that frequency cannot miss a 4.2 s preamble; a receiver 50 kHz away will not correlate it.

GUARDRAIL: the listener stream must be read live. Capturing it once at the end attributes every event to the wrong
frequency, which is how "preamble count" told us nothing earlier. This reads lines in a thread and timestamps them.
"""
import argparse
import pathlib
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

TX = REPO / "examples/apps/lora/loratx_ms_pre512.fs"
CLR = "NSSLO 2 >BYTE 255 >BYTE 255 >BYTE NSSHI"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", default="/dev/ttyUSB0")
    ap.add_argument("--peer", default="/dev/ttyUSB1")
    ap.add_argument("--from-mhz", dest="f0", type=float, default=869.34)
    ap.add_argument("--to-mhz", dest="f1", type=float, default=869.54)
    ap.add_argument("--step-khz", type=float, default=10.0)
    ap.add_argument("--hold", type=float, default=5.5)
    a = ap.parse_args()

    events = []                            # (monotonic time, kind)
    lock = threading.Lock()
    listener = subprocess.Popen(["meshtastic", "--port", a.peer, "--listen", "--debug"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    def reader():
        for line in listener.stdout:
            if "Ignore false preamble detection" in line:
                with lock: events.append((time.monotonic(), "pre"))
            elif "Ignore false header detection" in line:
                with lock: events.append((time.monotonic(), "hdr"))
    th = threading.Thread(target=reader, daemon=True)
    th.start()
    time.sleep(18)

    dev = Dev(port=a.ours)
    dev.reset()
    load(dev, TX)
    if dev.num("RADIO-INIT .", 40.0) != 1:
        listener.kill()
        raise SystemExit("our transmitter refused to configure")

    rows = []
    f = a.f0
    while f <= a.f1 + 1e-9:
        mhz = round(f, 3)
        w = round(mhz * 1e6 * 2 ** 25 / 32e6)
        dev.cmd(f"NSSLO 134 >BYTE {(w >> 24) & 255} >BYTE {(w >> 16) & 255} >BYTE {(w >> 8) & 255} >BYTE {w & 255} >BYTE NSSHI",
                10.0, allow_error=True)
        dev.cmd(CLR, 10.0, allow_error=True)
        t0 = time.monotonic()
        dev.num("GO .", 90.0)
        time.sleep(a.hold)
        t1 = time.monotonic()
        with lock:
            n_pre = sum(1 for t, k in events if k == "pre" and t0 <= t <= t1)
            n_hdr = sum(1 for t, k in events if k == "hdr" and t0 <= t <= t1)
        rows.append((mhz, n_pre, n_hdr))
        print(f"  {mhz:.3f} MHz -> preamble {n_pre}, header {n_hdr}", flush=True)
        f += a.step_khz / 1000.0

    listener.kill()
    with lock:
        total = len(events)
    print(f"  totals: {total} events; best:", max(rows, key=lambda r: (r[1] + r[2], -abs(r[0] - 869.44))))
    dev.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
