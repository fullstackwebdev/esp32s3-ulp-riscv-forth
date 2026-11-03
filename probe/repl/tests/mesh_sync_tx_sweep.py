#!/usr/bin/env python3
"""Brute-force the 0x0740/0x0741 pair on TRANSMIT against the stock node, one frame per candidate.

    python3 tests/mesh_sync_tx_sweep.py --ours /dev/ttyUSB0 --peer /dev/ttyUSB1 [--msb 14 2b]

RadioLib calls 0x0741 "undocumented control bits, required for compatibility purposes", and our receiver only ever
locked with LSB 0x24 - which is not enough to know what the PEER's receiver expects: the only witness for that is the
peer itself decoding us. So transmit one frame per candidate and let it answer. The registers are written per attempt,
so no file is regenerated per value.

GUARDRAIL: clear the IRQ before every SetTx. With a stale TxDone still latched, WAITX returns instantly and the next
SetTx is issued while the radio is still in TX, which aborts the frame - that is how earlier sweeps produced frames
that were never actually on the air.
"""
import argparse
import json
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

TX = REPO / "examples/apps/lora/loratx_ms_clamp.fs"     # 869.480 MHz, channel 0x08, clamp applied, 32 B frame
CLR = "NSSLO 2 >BYTE 255 >BYTE 255 >BYTE NSSHI"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", default="/dev/ttyUSB0")
    ap.add_argument("--peer", default="/dev/ttyUSB1")
    ap.add_argument("--msb", nargs="+", default=["14", "2b"])
    ap.add_argument("--gap", type=float, default=2.0)
    a = ap.parse_args()
    listener = subprocess.Popen(["meshtastic", "--port", a.peer, "--listen", "--debug"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(18)
    dev = Dev(port=a.ours)
    dev.reset()
    load(dev, TX)
    init = dev.num("RADIO-INIT .", 40.0)
    if init != 1:
        listener.kill()
        raise SystemExit("our transmitter refused to configure")
    found = []
    for msb in a.msb:
        for lsb in range(256):
            dev.cmd(f"NSSLO 13 >BYTE 7 >BYTE 64 >BYTE {int(msb, 16)} >BYTE {lsb} >BYTE NSSHI", 10.0, allow_error=True)
            dev.cmd(CLR, 10.0, allow_error=True)
            dev.num("GO .", 60.0)
            time.sleep(a.gap)
        print(f"  finished sweep for MSB 0x{msb}", flush=True)
    time.sleep(10)
    listener.kill()
    log = listener.communicate()[0] or ""
    out = REPO / "probe/results/sync_tx_sweep.log"
    out.write_text(log)
    hits = [l for l in log.splitlines() if "hi from ulp" in l]
    print(json.dumps({"decoded_lines": len(hits), "log": str(out)}))
    for l in hits[:10]:
        print("   ", l.strip()[:120])
    return 0


if __name__ == "__main__":
    sys.exit(main())
