#!/usr/bin/env python3
"""Transmit the Meshtastic frame from one of our boards and receive it on the other, byte for byte.

    python3 tests/mesh_loop_check.py [--tx /dev/ttyUSB1] [--rx /dev/ttyUSB0]

Both boards must be running OUR firmware (`idf.py -p <port> flash`); this does not involve Meshtastic firmware at all.
It answers one question the peer's silence cannot: are the bytes our radio actually radiates the frame we built, at the
peer's carrier (869.480 MHz), its preset (SF11/BW250/CR4-5) and its sync pair (0x2B,0x24)? It also reports the received
level, so the link budget is a measurement rather than a guess.
"""
import argparse
import json
import pathlib
import re
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
from devio import Dev                          # noqa: E402
from lora_frame_phase import load              # noqa: E402

TX_PHASE = REPO / "examples/apps/lora/loratx_ms_sf11bw5sync2b24f869.48.fs"
RX_INIT = REPO / "examples/apps/lora/lorainit.fs"
RX_WORDS = REPO / "examples/apps/lora/lora_rx.fs"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:50s} {detail}")
    if not ok:
        fails.append(name)


def last_numbers(reply, count):
    lines = [l for l in reply.splitlines() if l.strip()]
    if not lines:
        return []
    # the board echoes the typed line first; the values follow it
    vals = re.findall(r"-?\d+", lines[-1].replace("ok", " "))
    return [int(v) for v in vals][-count:] if vals else []


def read_bytes(dev, count):
    """GetRxBufferStatus then ReadBuffer via the file's own `RL RB`, which prints the bytes space-separated."""
    # GUARDRAIL: do not hand-roll the dump with `RD-BYTE .` - the board prints values with NO separator
    # ("255255255255"), so any whitespace split yields nothing and a naive fixed-width split invents numbers over 255.
    # `RDUMP` emits a space after every byte; use it.
    rep = dev.cmd("RL RB", 30.0, allow_error=True)
    vals = []
    for line in rep.splitlines()[1:]:                       # skip the echoed command
        vals += [int(x) for x in line.split() if x.isdigit()]
    return bytes(vals[:count])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tx", default="/dev/ttyUSB1")
    ap.add_argument("--rx", default="/dev/ttyUSB0")
    a = ap.parse_args()
    ref = json.loads((HERE / "data/mesh_packet.json").read_text())
    frame = bytes.fromhex(ref["frame"])
    rx = Dev(port=a.rx)
    rx.reset()
    load(rx, RX_INIT)
    load(rx, RX_WORDS)
    check("receiver configures at the measured carrier", rx.num("RADIO-INIT .", 40.0) == 1)
    tx = Dev(port=a.tx)
    tx.reset()
    load(tx, TX_PHASE)
    check("transmitter configures", tx.num("RADIO-INIT .", 40.0) == 1)
    rx.cmd("RC SR", 10.0, allow_error=True)
    tx.cmd("NSSLO 2 >BYTE 255 >BYTE 255 >BYTE NSSHI", 10.0, allow_error=True)   # clear stale IRQs, or WAITX returns instantly
    status = tx.num("GO .", 60.0)
    irq, deadline = 0, time.time() + 10
    while time.time() < deadline:
        irq = rx.num("IQ .", 20.0)
        if irq & 0x0002:
            break
        time.sleep(0.03)
    check("receiver reports RxDone", bool(irq & 0x0002), f"IRQ 0x{irq:04x}")
    if not (irq & 0x0002):
        print(f"  transmitter status 0x{status:02x}")
        return 1
    got = bytes(read_bytes(rx, len(frame)))
    check("on-air bytes equal the built frame", got == frame, got.hex())
    # GetPacketStatus(0x14): status, RssiPkt, SnrPkt (snr/4), SignalRssiPkt
    rx.cmd("NSSLO 20 >BYTE", 10.0, allow_error=True)
    st = last_numbers(rx.cmd("RD-BYTE . RD-BYTE . RD-BYTE . RD-BYTE .", 15.0, allow_error=True), 4)
    rx.cmd("NSSHI", 10.0, allow_error=True)
    if len(st) >= 3:
        print(f"  link: rssi {-st[1] // 2} dBm, snr {st[2] / 4:+.2f} dB (signal rssi {-st[3] // 2} dBm)")
    rx.close()
    tx.close()
    print(f"\n  {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
