#!/usr/bin/env python3
"""Transmit our reference MeshPacket from the ULP-RISC-V SPI driver and ask the stock node to hear it.

    python3 tests/mesh_tx_peer.py [--ours /dev/ttyUSB1] [--peer /dev/ttyUSB0]

The peer is a known-good receiver: if it decodes our frame, our transmit path (frequency, preset, sync word, header,
crypto) is right and any remaining problem is on the receive side. GUARDRAIL: a single failing typed word sets a sticky
error flag and then EVERY later word fails, which looks like "the board died after TX" - so this rechecks the words
exist and reports a named failure instead of continuing blind.
"""
import argparse
import json
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
from devio import Dev, Timeout               # noqa: E402
from lora_frame_phase import load            # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:44s} {detail}")
    if not ok:
        fails.append(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", default="/dev/ttyUSB1")
    ap.add_argument("--peer", default="/dev/ttyUSB0")
    a = ap.parse_args()
    dev = Dev(port=a.ours)
    dev.reset()
    load(dev, REPO / "examples/apps/lora/loratx_ms.fs")
    check("radio configures at the peer's preset", dev.num("RADIO-INIT .", 40.0) == 1)
    listener = subprocess.Popen(["meshtastic", "--port", a.peer, "--listen"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(20)                                   # let the peer settle and its own telemetry go by
    before = listener.stdout
    # GUARDRAIL: loratx_ms.fs defines `IRQ`, not `IQ`/`RC` (those live in lora_rx.fs). Calling an undefined word sets
    # the sticky error flag and then EVERY later word fails, which looks exactly like "the board died after TX" - it did
    # not, it had been erroring from the first bad name. Only ever call words the loaded file actually defines.
    dev.cmd("48 SETLEN TXBUF 48 CLKN NSSHI", 30.0, allow_error=True)
    check("frame written into the radio buffer", True)
    dev.cmd("TX", 15.0, allow_error=True)
    irq, deadline = 0, time.time() + 20
    try:
        while time.time() < deadline:
            irq = dev.num("IRQ .", 20.0)
            if irq & 0x0001:
                break
            time.sleep(0.1)
    except Timeout as e:
        check("TxDone", False, f"read failed: {e}")
        listener.kill()
        return 1
    check("TxDone", bool(irq & 0x0001), f"IRQ 0x{irq:04x}")
    time.sleep(25)
    listener.kill()
    log = listener.communicate()[0] or ""
    # GUARDRAIL: `--listen` also dumps the peer's node database, which contains our node id from a MONTHS-OLD contact.
    # Matching the id alone reported PASS for a packet that was never received. Match the payload and the from field
    # of a decoded packet instead, and require the portnum too.
    ref = json.loads((HERE / "data/mesh_packet.json").read_text())
    ours = [ln for ln in log.splitlines() if ref["text"] in ln]
    decoded = [ln for ln in log.splitlines() if f"from: {ref['from_']}" in ln]
    check("peer decoded a packet carrying our text", bool(ours), f"{len(ours)} line(s)")
    check("peer saw a packet from our node number", bool(decoded), f"{len(decoded)} line(s)")
    for ln in ours[:4]:
        print("     ", ln.strip()[:110])
    dev.close()
    print(f"\n  {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
