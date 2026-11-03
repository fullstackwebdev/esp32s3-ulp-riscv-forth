#!/usr/bin/env python3
"""Measure the stock node's RECEIVER parameters (SF/BW) with a preamble-only sweep.

    python3 tests/mesh_peer_rx_params.py --ours /dev/ttyUSB1 --peer /dev/ttyUSB0

Why: a receiver answers a preamble when, and only when, the chirp slope and bandwidth match. Sync words and framing come
later. So transmitting a LONG preamble across every candidate (SF, BW) and counting the peer's own preamble records
measures its receive configuration directly - no decoding, no crypto, no channel hash involved.

GUARDRAIL: read the listener stream LIVE (thread + timestamps). Reading it once at the end attributes every event to the
wrong candidate, which is exactly how an earlier preamble count told us nothing.
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

TX = REPO / "examples/apps/lora/loratx_ms_clamp.fs"
BW = {125: 4, 250: 5, 500: 6}              # RadioLib: 125 kHz = 0x04, 250 = 0x05, 500 = 0x06


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", default="/dev/ttyUSB1")
    ap.add_argument("--peer", default="/dev/ttyUSB0")
    ap.add_argument("--freq", type=float, default=869.48)
    ap.add_argument("--preamble", type=int, default=256)
    ap.add_argument("--hold", type=float, default=5.0)
    a = ap.parse_args()

    events = []
    lock = threading.Lock()
    listener = subprocess.Popen(["meshtastic", "--port", a.peer, "--listen", "--debug"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    def reader():
        for line in listener.stdout:
            if "Ignore false preamble detection" in line:
                with lock: events.append((time.monotonic(), "pre"))
            elif "Ignore false header detection" in line:
                with lock: events.append((time.monotonic(), "hdr"))
    threading.Thread(target=reader, daemon=True).start()
    time.sleep(18)

    dev = Dev(port=a.ours)
    dev.reset()
    load(dev, TX)
    if dev.num("RADIO-INIT .", 40.0) != 1:
        listener.kill()
        raise SystemExit("our transmitter refused to configure")
    w = round(a.freq * 1e6 * 2 ** 25 / 32e6)
    dev.cmd("NSSLO 128 >BYTE 0 >BYTE NSSHI", 10.0, allow_error=True)
    dev.cmd(f"NSSLO 134 >BYTE {(w >> 24) & 255} >BYTE {(w >> 16) & 255} >BYTE {(w >> 8) & 255} >BYTE {w & 255} >BYTE NSSHI",
            10.0, allow_error=True)
    best = []
    for bw_khz in (250, 125, 500):
        for sf in (11, 12, 10, 9):
            p_msb, p_lsb = (a.preamble >> 8) & 0xFF, a.preamble & 0xFF
            dev.cmd(f"NSSLO 139 >BYTE {sf} >BYTE {BW[bw_khz]} >BYTE 1 >BYTE 0 >BYTE NSSHI", 10.0, allow_error=True)
            dev.cmd(f"NSSLO 140 >BYTE {p_msb} >BYTE {p_lsb} >BYTE 0 >BYTE 32 >BYTE 1 >BYTE 0 >BYTE NSSHI",
                    10.0, allow_error=True)
            dev.cmd("NSSLO 2 >BYTE 255 >BYTE 255 >BYTE NSSHI", 10.0, allow_error=True)
            t0 = time.monotonic()
            dev.num("GO .", 90.0)
            time.sleep(a.hold)
            t1 = time.monotonic()
            with lock:
                n_pre = sum(1 for t, k in events if t0 <= t <= t1)
            print(f"  SF{sf} BW{bw_khz:<4d} -> preamble/header events {n_pre}", flush=True)
            best.append((n_pre, sf, bw_khz))
    listener.kill()
    dev.close()
    best.sort(reverse=True)
    print("  best candidate:", best[0] if best else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
