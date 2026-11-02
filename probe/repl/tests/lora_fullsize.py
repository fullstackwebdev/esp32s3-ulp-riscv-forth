#!/usr/bin/env python3
"""A full-size LoRa packet: 221 bytes on the air, decoded byte-for-byte by the peer.

    python3 tests/lora_fullsize.py [--a /dev/ttyUSB0] [--b /dev/ttyUSB1]

WHAT THIS PROVES
  The frame is not limited to the 26-byte demo. `SETLEN` in loratx.fs takes the payload length at run time, the
  bytes are clocked into the chip's buffer through WriteBuffer, and the peer reads all of them out of its own RX
  buffer. 221 B is 16 B header + 3 B portnum + 2 B protobuf length + 200 B payload - a Meshtastic Data frame
  with a 200-byte body, which is where the 255 B limit actually lives (LoRa caps the whole packet at 255).

GUARDRAIL: the receiver's SetPacketParams length must equal the frame's, not "any": measured on this board,
a receiver left at 4 was deaf to a 26-byte frame and one left at 255 was deaf too, while the frame's own
length worked.

GUARDRAIL: bytes go in four `>BYTE`s per typed line. Sixteen on one line is 76 B and the input ring drops it
silently, which is how the first scratch probe reported the buffer's leftovers as its answer.
"""
import argparse
import pathlib
import re
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "tools"))
from devio import Dev                      # noqa: E402
from lintgate import require_clean         # noqa: E402

TX_PHASE = REPO / "examples/apps/lora/loratx.fs"
INIT_PHASE = REPO / "examples/apps/lora/lorainit.fs"
RX_WORDS = REPO / "examples/apps/lora/lora_rx.fs"

PAYLOAD_LEN = 200
# 16 B Meshtastic header: broadcast, from 0A0A0A0A, id CAFE0100, flags/channel/next_hop/relay zero
HEADER = [255, 255, 255, 255, 10, 10, 10, 10, 202, 254, 1, 0, 0, 0, 0, 0]
DATA = [8, 128, 2, 18] + [PAYLOAD_LEN & 0xFF]          # portnum 256, payload length
BODY = [(i * 7 + 3) & 0xFF for i in range(PAYLOAD_LEN)]
FRAME = HEADER + DATA + BODY
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:48s} {detail}")
    if not ok:
        fails.append(name)


def last_line(rep):
    lines = [l.strip() for l in rep.strip().splitlines() if l.strip()]
    return lines[-1] if lines else ""


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
                    raise SystemExit(f"{path.name}: `{name}` did not appear after its definition")
                pend, name = [], None
            continue
        if "ERR" in dev.cmd(line, 10.0, allow_error=True):
            raise SystemExit(f"{path.name}: refused at interpret level: {line[:40]!r}")
    return True


def write_buffer(dev, offset, data):
    """WriteBuffer(0x0E) with the NSS-low transaction spread over lines of four `>BYTE`s."""
    dev.cmd(f"NSSLO 14 >BYTE {offset} >BYTE", 10.0, allow_error=True)
    for i in range(0, len(data), 4):
        dev.cmd(" ".join(f"{b} >BYTE" for b in data[i:i + 4]), 10.0, allow_error=True)
    dev.cmd("NSSHI", 10.0, allow_error=True)


def read_bytes(dev, offset, n):
    dev.cmd(f"NSSLO 30 >BYTE {offset} >BYTE RD-BYTE DROP", 10.0, allow_error=True)
    out = []
    for _ in range(n):
        out.append(dev.num("RD-BYTE .", 8.0) & 0xFF)
    dev.cmd("NSSHI", 10.0, allow_error=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="/dev/ttyUSB0")
    ap.add_argument("--b", default="/dev/ttyUSB1")
    a = ap.parse_args()
    require_clean([TX_PHASE], "--repl", where="tx-phase")
    require_clean([INIT_PHASE], "--repl", where="init-phase")
    require_clean([RX_WORDS], "--repl", where="rx-words", use=[INIT_PHASE])

    B = Dev(port=a.b)
    B.reset()
    load(B, INIT_PHASE)
    load(B, RX_WORDS)
    h0, l0 = B.num("HERE ."), B.num("LATEST .")
    SETLEN = [": SETLEN ( n -- )", "  NSSLO 140 >BYTE 0 >BYTE 16 >BYTE 0 >BYTE",
              "  >BYTE 1 >BYTE 0 >BYTE NSSHI ;"]
    for line in SETLEN:
        B.cmd(line, 10.0, allow_error=True)
    if not re.fullmatch(r"-?\d+\s+ok", last_line(B.cmd("' SETLEN .", 8.0, allow_error=True))):
        raise SystemExit("peer: SETLEN did not appear")
    print(f"  peer: {B.num('LATEST .') - h0} B of dictionary after init+rx words")
    check("peer radio configures", B.num("RADIO-INIT .", 30.0) == 1)
    B.num(f"{len(FRAME)} SETLEN .", 10.0)
    B.cmd("RC SR", 10.0, allow_error=True)
    mode = (B.num("STAT .", 15.0) >> 4) & 7
    check("peer is in RX", mode == 5, f"chipmode {mode}")

    A = Dev(port=a.a)
    A.reset()
    load(A, TX_PHASE)
    check("sender radio configures", A.num("RADIO-INIT .", 30.0) == 1)
    A.num(f"{len(FRAME)} SETLEN .", 10.0)
    write_buffer(A, 0, FRAME)
    A.cmd("TX", 10.0, allow_error=True)
    A.cmd("WAITX", 40.0, allow_error=True)
    irq = A.num("IRQ .", 15.0)
    check("TxDone after a full-size frame", bool(irq & 1), f"IRQ 0x{irq:04x} ({len(FRAME)} B)")
    A.close()

    irq_b, got = 0, []
    deadline = time.time() + 25
    while time.time() < deadline:
        irq_b = B.num("IQ .", 15.0)
        if irq_b & 2:
            break
        time.sleep(0.05)
    check("peer reports RxDone", bool(irq_b & 2), f"IRQ 0x{irq_b:04x}")
    if irq_b & 2:
        got = read_bytes(B, 0, len(FRAME))
        check("full-size frame length", len(got) == len(FRAME), f"{len(got)} B, expected {len(FRAME)}")
        check("header intact", got[:16] == HEADER, " ".join(f"{b:02x}" for b in got[:16]))
        check("protobuf prefix intact", got[16:21] == DATA, " ".join(f"{b:02x}" for b in got[16:21]))
        bad = [i for i, (x, y) in enumerate(zip(got[21:], BODY)) if x != y]
        check(f"{PAYLOAD_LEN}-byte payload byte-exact", not bad,
              f"first mismatch at body index {bad[0]}" if bad else "every byte matched")
    else:
        check("frame arrives at all", False, "no RxDone within 25 s")

    print(f"  {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
