#!/usr/bin/env python3
"""A Meshtastic-compatible frame: the CHIP encrypts, the air carries it, the peer's chip decrypts.

    python3 tests/mesh_frame.py [--a /dev/ttyUSB0] [--b /dev/ttyUSB1]

WHAT "COMPATIBLE" MEANS HERE, and what it does not.
  The frame is the one Meshtastic's own source describes (docs/31 Appendix J):
    * 16-byte PacketHeader: to/from/id/flags/channel/next_hop/relay
    * channel byte = xorHash(name) ^ xorHash(psk)  (0x08 for "LongFast")
    * sync word 0x2B, SF9 / BW125 / CR4-5, preamble 16, CRC on
    * payload = protobuf Data{portnum, payload}, encrypted with AES-128-CTR
    * nonce = packetId u64 LE || from u32 LE || zeros
    * key = the 16-byte PSK itself (Channels.cpp getKey at that length)
  Every one of those values comes from the fetched source, not from memory, and the ciphertext is judged against
  `openssl enc -aes-128-ctr`. What this does NOT prove is that a Meshtastic radio decoded it - none is on this bench.

WHY THE BYTES MOVE THROUGH THE HOST. The cipher is 1328 B and the radio driver plus receive words are 1177 B, so
they do not fit one 1328 B dictionary together; the four-phase chain that fixes that is built but its dispatch
still cycles (docs/31). So the harness carries the ciphertext from the encrypting session to the transmitting
session. The CRYPTO is done by the coprocessor on both ends.
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
from devio import Dev                      # noqa: E402
from lintgate import require_clean         # noqa: E402

V = json.load(open(HERE / "data" / "mesh_frame.json"))
CIPHER = REPO / "examples/apps/lora/lora_aes.fs"
TX = REPO / "examples/apps/lora/loratx.fs"
INIT = REPO / "examples/apps/lora/lorainit.fs"
RXW = REPO / "examples/apps/lora/lora_rx.fs"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:50s} {detail}")
    if not ok:
        fails.append(name)


def last_line(rep):
    ls = [l.strip() for l in rep.strip().splitlines() if l.strip()]
    return ls[-1] if ls else ""


def load(dev, path):
    pend, name = [], None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("\\"):
            continue
        m = re.match(r":\s+(\S+)", line)
        if m and not pend:
            name = m.group(1)
        if name:
            pend.append(line)
            if line.endswith(";"):
                for one in pend:
                    dev.cmd(one, 10.0, allow_error=True)
                if not re.fullmatch(r"-?\d+\s+ok", last_line(dev.cmd(f"' {name} .", 8.0, allow_error=True))):
                    raise SystemExit(f"{path.name}: `{name}` did not appear")
                pend, name = [], None
            continue
        dev.cmd(line, 10.0, allow_error=True)


def seed_state(dev, data):
    for i, b in enumerate(data):
        dev.cmd(f"{b} {i} ST + C!", 8.0, allow_error=True)


def xor_state(dev, data):
    """XOR the 16-byte state with `data` IN THE CHIP, one typed line per byte."""
    for i, b in enumerate(data):
        dev.cmd(f"ST {i} + C@ {b} XOR ST {i} + C! ", 8.0, allow_error=True)


def read_state(dev, n=16):
    return [dev.num(f"{i} ST + C@ .", 8.0) & 0xFF for i in range(n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="/dev/ttyUSB0")
    ap.add_argument("--b", default="/dev/ttyUSB1")
    a = ap.parse_args()
    require_clean([CIPHER], "--repl", where="cipher")
    require_clean([TX], "--repl", where="tx")
    require_clean([INIT], "--repl", where="init")
    require_clean([RXW], "--repl", where="rx", use=[INIT])

    nonce = bytes.fromhex(V["nonce"])
    plain = bytes.fromhex(V["plain"])            # 11 bytes: 08 80 02 12 06 "hello!"
    header = bytes.fromhex(V["header"])
    frame = header + plain                        # clear header + protobuf = 27 bytes
    want_ct = bytes.fromhex(V["ct"])

    # ---- 1. the SENDER's chip encrypts ---------------------------------------------------------------
    A = Dev(port=a.a)
    A.reset()
    load(A, CIPHER)
    seed_state(A, nonce)
    A.cmd("AESB", 120.0, allow_error=True)        # keystream = AES(nonce)
    xor_state(A, plain)                           # ciphertext = keystream ^ plaintext
    ct = bytes(read_state(A, 16))[:len(plain)]
    check("the sender's chip encrypts to openssl's ciphertext", ct.hex() == want_ct.hex(), ct.hex())
    A.close()

    # ---- 2. the frame goes on the air ---------------------------------------------------------------
    A = Dev(port=a.a)
    A.reset()
    load(A, TX)
    check("sender radio configures", A.num("RADIO-INIT .", 30.0) == 1)
    A.num(f"{len(frame)} SETLEN .", 10.0)
    A.cmd("NSSLO 14 >BYTE 0 >BYTE", 10.0, allow_error=True)
    for i in range(0, len(frame), 4):
        A.cmd(" ".join(f"{b} >BYTE" for b in frame[i:i + 4]), 10.0, allow_error=True)
    A.cmd("NSSHI", 10.0, allow_error=True)
    A.cmd("TX", 10.0, allow_error=True)
    A.cmd("WAITX", 40.0, allow_error=True)
    check("TxDone for the 27-byte encrypted frame", bool(A.num("IRQ .", 15.0) & 1), f"{len(frame)} B")
    A.close()

    # ---- 3. the PEER receives it --------------------------------------------------------------------
    B = Dev(port=a.b)
    B.reset()
    load(B, INIT)
    load(B, RXW)
    check("peer radio configures", B.num("RADIO-INIT .", 30.0) == 1)
    for line in (": SETLEN ( n -- )", "  NSSLO 140 >BYTE 0 >BYTE 16 >BYTE 0 >BYTE",
                 "  >BYTE 1 >BYTE 0 >BYTE NSSHI ;"):
        B.cmd(line, 10.0, allow_error=True)
    B.num(f"{len(frame)} SETLEN .", 10.0)
    B.cmd("RC SR", 10.0, allow_error=True)
    irq = 0
    deadline = time.time() + 25
    while time.time() < deadline:
        irq = B.num("IQ .", 15.0)
        if irq & 2:
            break
        time.sleep(0.05)
    check("peer reports RxDone", bool(irq & 2), f"IRQ 0x{irq:04x}")
    air, got = [], []
    if irq & 2:
        B.cmd("NSSLO 30 >BYTE 0 >BYTE RD-BYTE DROP", 10.0, allow_error=True)
        got = [B.num("RD-BYTE .", 10.0) & 0xFF for _ in range(len(frame))]
        B.cmd("NSSHI", 10.0, allow_error=True)
        hdr_ok = bytes(got[:16]).hex() == header.hex()
        ct_ok = bytes(got[16:]).hex() == want_ct.hex()
        check("header is the Meshtastic layout (channel 0x%02x)" % V["channel"], hdr_ok, bytes(got[:16]).hex())
        check("payload on the air is the encrypted Data message", ct_ok, bytes(got[16:]).hex())
    B.close()

    # ---- 4. the PEER's chip decrypts ----------------------------------------------------------------
    if got:
        B = Dev(port=a.b)
        B.reset()
        load(B, CIPHER)
        seed_state(B, nonce)
        B.cmd("AESB", 120.0, allow_error=True)
        xor_state(B, bytes(got[16:]) + bytes(16 - len(got[16:])))
        back = bytes(read_state(B, 16))[:len(plain)]
        check("the peer's chip decrypts back to the protobuf", back.hex() == plain.hex(), back.hex())
        check("that plaintext is Data{portnum 256, \"hello!\"}", back == plain,
              " ".join(f"{b:02x}" for b in back))
        B.close()

    print(f"  {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
