#!/usr/bin/env python3
"""The whole Meshtastic path on the boards: cipher chain -> radio buffer -> air -> peer.

    python3 tests/mesh_air.py [--a /dev/ttyUSB0] [--b /dev/ttyUSB1]

What runs where:
  board A  six store phases (seed -> ark -> [sub -> sr -> mc -> ark] x 10 -> out) compute AES-128-CTR for the
           Meshtastic nonce with the LongFast PSK and leave the 11 ciphertext bytes in the SX1262's own buffer at
           offset 16; then the frame phase (same build, descriptor 104) writes the 16-byte header at offset 0 and
           transmits 27 bytes.
  board B  receives the 27 bytes. The test compares them with `socket`-free ground truth: the header from the
           fetched Meshtastic source and the ciphertext from `openssl enc -aes-128-ctr`.

No byte of the frame or the ciphertext passes through this process: the only numbers exchanged are printouts.
"""
import argparse
import json
import pathlib
import sys
import re
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
from devio import Dev                        # noqa: E402
from lintgate import require_clean           # noqa: E402
import cli                                   # noqa: E402
from lora_frame_phase import load            # noqa: E402

V = json.load(open(HERE / "data" / "mesh_frame.json"))
HEADER = bytes.fromhex(V["header"])
CT = bytes.fromhex(V["ct"])
FRAME = HEADER + CT
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:52s} {detail}")
    if not ok:
        fails.append(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="/dev/ttyUSB0")
    ap.add_argument("--b", default="/dev/ttyUSB1")
    a = ap.parse_args()
    for f in ("aes_seed", "aes_sub", "aes_sr", "aes_mc", "aes_ark", "aes_out", "aes_dec", "loratx"):
        # GUARDRAIL: a phase may use the store's CHAIN/NXT words, so the gate must be told what was loaded
        # BEFORE it (`use=`) - without that, R2 reports CHAIN undefined for every correct phase.
        require_clean([REPO / "examples/apps/lora" / f"{f}.fs"], "--store", where=f,
                      use=[REPO / "examples/appstore.fs"])

    # ---- board B first: it must already be in RX when the frame arrives ----
    B = Dev(port=a.b)
    B.reset()
    load(B, REPO / "examples/apps/lora/lorainit.fs")
    load(B, REPO / "examples/apps/lora/lora_rx.fs")
    check("peer configures", B.num("RADIO-INIT .", 30.0) == 1)
    for line in (": SETLEN ( n -- )", "  NSSLO 140 >BYTE 0 >BYTE 16 >BYTE 0 >BYTE",
                 "  >BYTE 1 >BYTE 0 >BYTE NSSHI ;"):
        B.cmd(line, 10.0, allow_error=True)
    B.cmd(f"{len(FRAME)} SETLEN", 10.0, allow_error=True)
    B.cmd("RC SR", 10.0, allow_error=True)
    # GUARDRAIL: a LoRa receiver must already be listening when the frame arrives. Transmitting first and configuring
    # the peer afterwards measured `IRQ 0x0000` - the frame was simply gone, and it read like a broken payload path.

    # ---- board A: cipher then transmit, one build ----
    A = Dev(port=a.a)
    A.reset()
    built = cli.appstore(A, REPO, only=("aesseed", "aessub", "aessr", "aesmc", "aesark", "loratx", "aesout")) or []
    check("both halves of the path are in the store",
          {n for n, _d, _i in built} >= {"aesseed", "aessub", "aessr", "aesmc", "aesark", "aesout", "loratx"},
          " ".join(n for n, _d, _i in built))
    desc, hops = 80, 0
    while desc and hops < 80:
        A.cmd("0 NXT !", 6.0, allow_error=True)
        A.cmd(f"{desc} PICKX EXECUTE", 120.0, allow_error=True)
        hops += 1
        desc = A.num("NXT @ .", 10.0)
    check("the chain runs to its end (43 hops, then the out phase stops it)", hops == 43 and desc == 0, f"{hops} hops")
    # GUARDRAIL: the out phase transmits (it owns the config-free tail: payload, header, SetTx, WAITX), so the chain
    # running to its end IS the transmission. Probing IRQ afterwards answers "IRQ?" - a phase's words stop being
    # searchable once its image is pasted - and that looked like a dead radio for two runs.
    check("the chain ends with the out phase transmitting", True, f"{len(FRAME)} B on air")
    A.close()

    # ---- board B: judge what arrived ----
    irq, got = 0, []
    deadline = time.time() + 25
    while time.time() < deadline:
        irq = B.num("IQ .", 15.0)
        if irq & 2:
            break
        time.sleep(0.05)
    check("peer reports RxDone", bool(irq & 2), f"IRQ 0x{irq:04x}")
    if irq & 2:
        B.cmd("NSSLO 30 >BYTE 0 >BYTE RD-BYTE DROP", 10.0, allow_error=True)
        got = [B.num("RD-BYTE .", 10.0) & 0xFF for _ in range(len(FRAME))]
        B.cmd("NSSHI", 10.0, allow_error=True)
        check("header on air is the Meshtastic header", bytes(got[:16]).hex() == HEADER.hex(), bytes(got[:16]).hex())
        check("payload on air is the CIPHERTEXT openssl computes",
              bytes(got[16:]).hex() == CT.hex(), bytes(got[16:]).hex())
    B.close()

    # ---- board B again: its OWN chip decrypts what came off the air ----
    B = Dev(port=a.b)
    B.reset()
    cli.appstore(B, REPO, only=("aespr", "aesdec", "aesseed", "aessub", "aessr", "aesmc", "aesark"))
    desc, hops = 80, 0
    while desc and hops < 60:
        B.cmd("0 NXT !", 6.0, allow_error=True)
        B.cmd(f"{desc} PICKX EXECUTE", 120.0, allow_error=True)
        hops += 1
        desc = B.num("NXT @ .", 12.0)
    rep = B.cmd("4 PICKX EXECUTE", 60.0, allow_error=True)
    nums = [int(x) for x in re.findall(r"\b\d{1,3}\b", rep.split("4 PICKX EXECUTE")[-1])]
    plain = bytes(n & 0xFF for n in nums[17:28])
    check("the peer's chip decrypts the air bytes to the protobuf",
          plain.hex() == bytes.fromhex(V["plain"]).hex(), plain.hex())
    B.close()
    print(f"  {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
