#!/usr/bin/env python3
"""Measure which frequency the stock node actually transmits on: tune, arm RX, ask it to broadcast, read the IRQ.

    python3 tests/mesh_freq_scan.py

Why this exists: preamble detections at 869.4 MHz could belong to any nearby LoRa traffic, not to the peer. Preamble
detection does not depend on the sync word, so sweeping the frequency while the peer transmits is the only way to tell
its real carrier from ambient noise. GUARDRAIL: never conclude "the preset is right" from a preamble alone - a bogus
sync match plus a header error looks exactly like a foreign network, and misled us for a whole sweep.
"""
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
from devio import Dev                        # noqa: E402
from lora_frame_phase import load            # noqa: E402

BITS = {0x0004: "pre", 0x0008: "sync", 0x0010: "hdrOK", 0x0020: "hdrERR", 0x0040: "crcERR", 0x0002: "RxDone"}
FRAMES = [868.1, 868.5, 868.8, 869.0, 869.1, 869.2, 869.3, 869.4, 869.5, 869.525, 869.6, 869.65]


def describe(irq):
    return " ".join(n for b, n in BITS.items() if irq & b) or "nothing"


def set_freq(dev, mhz):
    w = round(mhz * 1e6 * 2 ** 25 / 32e6)
    dev.cmd(f"NSSLO 134 >BYTE {(w >> 24) & 0xFF} >BYTE {(w >> 16) & 0xFF} >BYTE {(w >> 8) & 0xFF} >BYTE {w & 0xFF} >BYTE NSSHI",
            10.0, allow_error=True)


def main():
    dev = Dev(port="/dev/ttyUSB1")
    dev.reset()
    load(dev, REPO / "examples/apps/lora/lorainit.fs")
    load(dev, REPO / "examples/apps/lora/lora_rx.fs")
    if dev.num("RADIO-INIT .", 40.0) != 1:
        raise SystemExit("our radio did not configure")
    dev.cmd("NSSLO 128 >BYTE 0 >BYTE NSSHI", 10.0, allow_error=True)                       # standby
    dev.cmd("NSSLO 13 >BYTE 7 >BYTE 64 >BYTE 43 >BYTE 68 >BYTE NSSHI", 10.0, allow_error=True)  # sync 2b/44
    dev.cmd("NSSLO 139 >BYTE 11 >BYTE 5 >BYTE 1 >BYTE 0 >BYTE NSSHI", 10.0, allow_error=True)   # SF11 BW250 CR4/5
    dev.cmd("NSSLO 140 >BYTE 0 >BYTE 16 >BYTE 0 >BYTE 255 >BYTE 1 >BYTE 0 >BYTE NSSHI", 10.0, allow_error=True)
    for mhz in FRAMES:
        set_freq(dev, mhz)
        dev.cmd("RC SR", 10.0, allow_error=True)
        r = subprocess.run(["meshtastic", "--port", "/dev/ttyUSB0", "--sendtext", f"scan{mhz}"],
                           capture_output=True, text=True, timeout=120)
        sent = "ok" if r.returncode == 0 else f"rc={r.returncode}"
        irq, deadline = 0, time.time() + 8
        while time.time() < deadline:
            irq = dev.num("IQ .", 15.0)
            if irq & (0x0002 | 0x0020 | 0x0040):
                break
            time.sleep(0.05)
        print(f"  {mhz:8.3f} MHz  send={sent:6s} -> 0x{irq:04x}  {describe(irq)}")
        if irq & 0x0002:
            print(f"  MATCH: the peer transmits at {mhz} MHz")
            dev.close()
            return 0
    dev.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
