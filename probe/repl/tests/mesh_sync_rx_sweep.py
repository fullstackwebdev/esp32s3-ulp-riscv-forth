#!/usr/bin/env python3
"""Which 0x0740/0x0741 pair does the stock node actually TRANSMIT? Sweep our receiver's pair against it.

    python3 tests/mesh_sync_rx_sweep.py --ours /dev/ttyUSB0 --peer /dev/ttyUSB1

GUARDRAIL: no listener may be attached to the peer while it sends - a listener and `--sendtext` cannot share the port,
and that mistake silently produced "no decode" results earlier. RadioLib documents 0x0741 as "undocumented control
bits, required for compatibility purposes", so the only way to know which of the two bytes matters is to vary them
one at a time against a real transmitter.
"""
import argparse
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
from devio import Dev                      # noqa: E402
from lora_frame_phase import load          # noqa: E402

PAIRS = [("2B", "44"), ("2B", "24"), ("2B", "00"), ("14", "24"), ("2B", "2B"), ("14", "44")]
BITS = {0x0002: "RxDone", 0x0004: "pre", 0x0008: "sync", 0x0010: "hdrOK", 0x0020: "hdrERR", 0x0040: "crcERR"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", default="/dev/ttyUSB0")
    ap.add_argument("--peer", default="/dev/ttyUSB1")
    ap.add_argument("--freq", default="869.480")
    a = ap.parse_args()
    dev = Dev(port=a.ours)
    dev.reset()
    load(dev, REPO / "examples/apps/lora/lorainit.fs")
    load(dev, REPO / "examples/apps/lora/lora_rx.fs")
    if dev.num("RADIO-INIT .", 40.0) != 1:
        raise SystemExit("our receiver refused to configure")
    w = round(float(a.freq) * 1e6 * 2 ** 25 / 32e6)
    dev.cmd("NSSLO 128 >BYTE 0 >BYTE NSSHI", 10.0, allow_error=True)                       # standby
    dev.cmd(f"NSSLO 134 >BYTE {(w >> 24) & 255} >BYTE {(w >> 16) & 255} >BYTE {(w >> 8) & 255} >BYTE {w & 255} >BYTE NSSHI",
            10.0, allow_error=True)
    dev.cmd("NSSLO 139 >BYTE 11 >BYTE 5 >BYTE 1 >BYTE 0 >BYTE NSSHI", 10.0, allow_error=True)
    dev.cmd("NSSLO 140 >BYTE 0 >BYTE 16 >BYTE 0 >BYTE 255 >BYTE 1 >BYTE 0 >BYTE NSSHI", 10.0, allow_error=True)
    for msb, lsb in PAIRS:
        dev.cmd(f"NSSLO 13 >BYTE 7 >BYTE 64 >BYTE 0x{msb} >BYTE 0x{lsb} >BYTE NSSHI", 10.0, allow_error=True) \
            if False else dev.cmd(f"NSSLO 13 >BYTE 7 >BYTE 64 >BYTE {int(msb,16)} >BYTE {int(lsb,16)} >BYTE NSSHI", 10.0, allow_error=True)
        best = 0
        for attempt in range(2):
            dev.cmd("RC SR", 10.0, allow_error=True)
            subprocess.run(["meshtastic", "--port", a.peer, "--sendtext", f"sync {msb}{lsb}"],
                           capture_output=True, timeout=150)
            irq, deadline = 0, time.time() + 9
            while time.time() < deadline:
                irq = dev.num("IQ .", 15.0)
                if irq & (0x0002 | 0x0020 | 0x0040):
                    break
                time.sleep(0.03)
            best |= irq
        hit = " ".join(n for b, n in BITS.items() if best & b) or "nothing"
        print(f"  0x0740={msb} 0x0741={lsb} -> IRQ 0x{best:04x}  {hit}", flush=True)
    dev.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
