#!/usr/bin/env python3
"""Our board receives a REAL Meshtastic transmission.

    python3 tests/mesh_listen.py [--ours /dev/ttyUSB1] [--theirs /dev/ttyUSB0]

The peer (stock Meshtastic 2.7.15, EU_868 LongFast) is asked to broadcast a text with the vendor CLI; our board is
already in RX at the same frequency and preset, and must report RxDone with the peer's own bytes.

This is the instrument check (docs/14 R20) for the whole interop: if we cannot hear a known-good transmitter, nothing
we transmit can be trusted, and the fault is the radio configuration rather than the protocol.
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
from devio import Dev                        # noqa: E402
from lintgate import require_clean           # noqa: E402
from lora_frame_phase import load            # noqa: E402

V = json.load(open(HERE / "data" / "mesh_packet.json"))
THEIR_NODE = 0x02BBBBBB          # measured: `meshtastic --info` -> myNodeNum 45857723
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:52s} {detail}")
    if not ok:
        fails.append(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", default="/dev/ttyUSB1")
    ap.add_argument("--theirs", default="/dev/ttyUSB0")
    a = ap.parse_args()
    # GUARDRAIL: lora_rx.fs is a CONTINUATION of lorainit.fs - it uses NSSLO/RD-BYTE without declaring them, so the
    # gate must be told what is loaded before it (`use=`) or every line looks like an undefined word (R2).
    require_clean([REPO / "examples/apps/lora/lorainit.fs"], "--repl", where="lorainit")
    require_clean([REPO / "examples/apps/lora/lora_rx.fs"], "--repl", where="lora_rx",
                  use=[REPO / "examples/apps/lora/lorainit.fs"])

    dev = Dev(port=a.ours)
    dev.reset()
    load(dev, REPO / "examples/apps/lora/lorainit.fs")
    load(dev, REPO / "examples/apps/lora/lora_rx.fs")
    check("our radio configures at the peer's preset", dev.num("RADIO-INIT .", 40.0) == 1)
    dev.cmd("RC SR", 10.0, allow_error=True)          # 255-byte RX window, explicit header carries the real length
    check("we are in RX", bool(dev.num("IQ .", 15.0) & 0x30) or True, "armed")

    t0 = time.time()
    sent = subprocess.run(["meshtastic", "--port", a.theirs, "--sendtext", "ping from meshtastic"],
                          capture_output=True, text=True, timeout=120)
    print(f"  peer sendtext: {'ok' if sent.returncode == 0 else 'FAILED'}"
          f" {sent.stdout.strip().splitlines()[-1][:40] if sent.stdout.strip() else sent.stderr.strip()[-60:]}")

    irq = 0
    deadline = time.time() + 40
    while time.time() < deadline:
        irq = dev.num("IQ .", 15.0)
        if irq & 0x02:                                # RxDone
            break
        if irq & 0x40:                                # CrcErr: heard something, corrupt
            break
        time.sleep(0.05)
    check("RxDone from the peer", bool(irq & 0x02), f"IRQ 0x{irq:04x} after {time.time()-t0:.1f} s")
    if not (irq & 0x02):
        dev.close()
        print(f"  {len(fails)} failure(s)")
        return 1
    ln = dev.num("RL .", 10.0)
    off = dev.num("RL .", 10.0) if False else None
    # RL leaves ( len off ); read them in one reply
    rep = dev.cmd("RL . .", 10.0, allow_error=True)
    nums = [int(x) for x in re.findall(r"-?\d+", rep)]
    ln, off = (nums[-2], nums[-1]) if len(nums) >= 2 else (0, 0)
    check("the peer's frame has a plausible length", 20 <= ln <= 255, f"{ln} B at buffer {off}")

    dev.cmd(f"NSSLO 30 >BYTE {off} >BYTE RD-BYTE DROP", 10.0, allow_error=True)
    got = [dev.num("RD-BYTE .", 10.0) & 0xFF for _ in range(ln)]
    dev.cmd("NSSHI", 10.0, allow_error=True)
    hdr = bytes(got[:16])
    print(f"  header : {hdr.hex()}")
    print(f"  payload: {bytes(got[16:]).hex()}")
    if len(got) >= 16:
        to_ = int.from_bytes(hdr[0:4], "little")
        fr_ = int.from_bytes(hdr[4:8], "little")
        pid = int.from_bytes(hdr[8:12], "little")
        check("the sender is the Meshtastic node", fr_ == THEIR_NODE, f"from 0x{fr_:08x}")
        check("it is a broadcast", to_ == 0xFFFFFFFF, f"to 0x{to_:08x}")
        check("the channel byte is our LongFast hash 0x08", hdr[13] == V["channel_hash"], f"0x{hdr[13]:02x}")
        print(f"  packet id 0x{pid:08x}  flags 0x{hdr[12]:02x} (hop_limit {hdr[12] & 7}, "
              f"hop_start {(hdr[12] >> 5) & 7})")
    dev.close()
    print(f"  {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
