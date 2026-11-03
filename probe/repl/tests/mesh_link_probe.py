#!/usr/bin/env python3
"""Find the working (sync pair, modem) combination against the real node, one clean cycle per attempt.

    python3 tests/mesh_link_probe.py

Each attempt: SetStandby -> write the sync pair -> SetModulationParams -> SetPacketParams -> ClearIrq -> SetRx, then ask
the peer to broadcast and read the IRQ. GUARDRAIL: the earlier sweeps wrote registers and re-issued SetRx while the radio
was STILL IN RX, where register writes can be ignored and SetRx is an error - the results were unstable and pointed at
several combinations at once. Standby first, every single time.
"""
import pathlib
import re
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
SYNC_PAIRS = [(0x14, 0x24)]   # measured: only this pair ever reached the header
MODEMS = [(11, 5, 1, 0), (11, 5, 1, 1), (11, 4, 1, 0), (11, 4, 1, 1), (9, 5, 1, 0), (9, 4, 1, 0), (12, 4, 1, 1)]


def describe(irq):
    return " ".join(n for b, n in BITS.items() if irq & b) or "nothing"


def main():
    dev = Dev(port="/dev/ttyUSB1")
    dev.reset()
    load(dev, REPO / "examples/apps/lora/lorainit.fs")
    load(dev, REPO / "examples/apps/lora/lora_rx.fs")
    if dev.num("RADIO-INIT .", 40.0) != 1:
        raise SystemExit("our radio did not configure")
    for msb, lsb in SYNC_PAIRS:
        for sf, bw, cr, ldro in MODEMS:
            dev.cmd("NSSLO 128 >BYTE 0 >BYTE NSSHI", 10.0, allow_error=True)          # SetStandby(RC)
            dev.cmd(f"NSSLO 13 >BYTE 7 >BYTE 64 >BYTE {msb} >BYTE {lsb} >BYTE NSSHI", 10.0, allow_error=True)
            dev.cmd(f"NSSLO 139 >BYTE {sf} >BYTE {bw} >BYTE {cr} >BYTE {ldro} >BYTE NSSHI", 10.0, allow_error=True)
            dev.cmd("NSSLO 140 >BYTE 0 >BYTE 16 >BYTE 0 >BYTE 255 >BYTE 1 >BYTE 0 >BYTE NSSHI", 10.0, allow_error=True)
            dev.cmd("RC SR", 10.0, allow_error=True)
            subprocess.run(["meshtastic", "--port", "/dev/ttyUSB0", "--sendtext", "linktest"],
                           capture_output=True, text=True, timeout=120)
            irq, deadline = 0, time.time() + 12
            while time.time() < deadline:
                irq = dev.num("IQ .", 15.0)
                if irq & (0x0002 | 0x0020 | 0x0040):
                    break
                time.sleep(0.05)
            print(f"  sync {msb:02x}/{lsb:02x} sf{sf} bw{bw} cr{cr} ldro{ldro} -> 0x{irq:04x}  {describe(irq)}")
            if irq & 0x0002:
                print(f"  MATCH: sync {msb:02x}/{lsb:02x}, sf{sf} bw{bw} cr{cr} ldro{ldro}")
                dev.close()
                return 0
    dev.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
