#!/usr/bin/env python3
"""Which modulation settings does the stock node really transmit with? Measured, one variable at a time.

    python3 tests/mesh_modem_probe.py [--ours /dev/ttyUSB1] [--theirs /dev/ttyUSB0]

We already know: preamble is detected (so frequency and bandwidth are close), and with sync LSB 0x24 we reach the
HEADER but it errors (IRQ 0x0020). In LoRa a header error means the modulation settings do not match - SF, CR or the
low-data-rate optimisation - never the payload. So hold the sync at the pair that reaches the header and vary those.
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
from devio import Dev                        # noqa: E402
from lora_frame_phase import load            # noqa: E402

BITS = {0x0004: "pre", 0x0008: "sync", 0x0010: "hdrOK", 0x0020: "hdrERR",
        0x0040: "crcERR", 0x0002: "RxDone"}


def describe(irq):
    return " ".join(n for b, n in BITS.items() if irq & b) or "nothing"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", default="/dev/ttyUSB1")
    ap.add_argument("--theirs", default="/dev/ttyUSB0")
    a = ap.parse_args()
    dev = Dev(port=a.ours)
    dev.reset()
    load(dev, REPO / "examples/apps/lora/lorainit.fs")
    load(dev, REPO / "examples/apps/lora/lora_rx.fs")
    if dev.num("RADIO-INIT .", 40.0) != 1:
        raise SystemExit("our radio did not configure")
    # sync pair that reaches the header, written properly through WriteRegisters(0x0D)
    dev.cmd("NSSLO 13 >BYTE 7 >BYTE 64 >BYTE 43 >BYTE 36 >BYTE NSSHI", 10.0, allow_error=True)
    variants = [("SF11 BW5 CR1 ldro0", 11, 5, 1, 0), ("SF11 BW5 CR1 ldro1", 11, 5, 1, 1),
                ("SF11 BW5 CR2 ldro0", 11, 5, 2, 0), ("SF12 BW5 CR1 ldro0", 12, 5, 1, 0),
                ("SF10 BW5 CR1 ldro0", 10, 5, 1, 0)]
    for tag, sf, bw, cr, ldro in variants:
        # SetModulationParams(0x8B): sf, bw, cr, ldro ; SetPacketParams(0x8C): preamble 16, explicit, len, crc on, iq std
        dev.cmd(f"NSSLO 139 >BYTE {sf} >BYTE {bw} >BYTE {cr} >BYTE {ldro} >BYTE NSSHI", 10.0, allow_error=True)
        dev.cmd("NSSLO 140 >BYTE 0 >BYTE 16 >BYTE 0 >BYTE 255 >BYTE 1 >BYTE 0 >BYTE NSSHI", 10.0, allow_error=True)
        dev.cmd("RC SR", 10.0, allow_error=True)
        subprocess.run(["meshtastic", "--port", a.theirs, "--sendtext", "modemtest"],
                       capture_output=True, text=True, timeout=120)
        irq, deadline = 0, time.time() + 12
        while time.time() < deadline:
            irq = dev.num("IQ .", 15.0)
            if irq & (0x0002 | 0x0020 | 0x0040):
                break
            time.sleep(0.05)
        print(f"  {tag:22s} -> IRQ 0x{irq:04x}  {describe(irq)}")
        if irq & 0x0002:
            print(f"  MATCH: {tag}")
            return 0
        dev.cmd("SR", 10.0, allow_error=True)
    dev.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
