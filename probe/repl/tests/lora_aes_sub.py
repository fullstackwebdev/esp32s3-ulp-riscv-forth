#!/usr/bin/env python3
"""Phase 1 of the AES chain: SubBytes + ShiftRows on the state in the SX1262 buffer.

    python3 tests/lora_aes_sub.py [--port /dev/ttyUSB0]

WHY THIS SHAPE. The cipher is 1328 B and a phase window is 999 B, so it is split across phases that hand the
16-byte state over in the radio's buffer - the one memory measured to survive an ADOPT (tests/lora_adopt.py).
This phase owns no storage (R16) and carries a read-only S-box table (allowed: it is part of the phase image).

WHAT IS COMPARED. The reference is computed here from the field definition, not remembered:
SubBytes then ShiftRows of state 00 01 .. 0f must be 63 6b 67 76 7c 6f 2b fe 77 c5 30 d7 7b f2 01 ab.

GUARDRAIL: the state goes IN and OUT through WriteBuffer/ReadBuffer at offset 224. A phase reads the same bytes the
next phase will read, so the test must not keep its own copy in the dictionary and compare against that.
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

PHASE = REPO / "examples/apps/lora/aes_sub.fs"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:46s} {detail}")
    if not ok:
        fails.append(name)


def sbox():
    def gmul(a, b):
        p = 0
        for _ in range(8):
            if b & 1:
                p ^= a
            hi = a & 0x80
            a = (a << 1) & 0xFF
            if hi:
                a ^= 0x1B
            b >>= 1
        return p
    inv = [0] * 256
    for x in range(1, 256):
        for y in range(1, 256):
            if gmul(x, y) == 1:
                inv[x] = y
                break
    rotl = lambda b, n: ((b << n) | (b >> (8 - n))) & 0xFF
    return [inv[x] ^ rotl(inv[x], 1) ^ rotl(inv[x], 2) ^ rotl(inv[x], 3) ^ rotl(inv[x], 4) ^ 0x63
            for x in range(256)]


def reference(state):
    S = sbox()
    sb = [S[b] for b in state]
    return [sb[(i & 3) * 4 + (((i >> 2) + (i & 3)) & 3)] for i in range(16)]


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    a = ap.parse_args()
    require_clean([PHASE], "--repl", where="aes-sub", use=[REPO / "examples/appstore.fs"])

    state = list(range(16))
    want = reference(state)
    dev = Dev(port=a.port)
    dev.reset()
    dev.cmd("CREATE NXT 0 ,", 8.0, allow_error=True)   # the store's resident cell, without appstore.fs (block-only)
    h0 = dev.num("HERE .")
    load(dev, PHASE)
    h1, l1 = dev.num("HERE .", 20.0), dev.num("LATEST .", 20.0)
    check("phase fits a 999 B window", h1 - h0 <= 999, f"{h1 - h0} B")
    check("phase leaves room for the rest of the chain", l1 - h1 >= 0, f"{l1 - h1} B free")

    dev.cmd("NSSLO 14 >BYTE 224 >BYTE", 10.0, allow_error=True)
    for i in range(0, 16, 4):
        dev.cmd(" ".join(f"{b} >BYTE" for b in state[i:i + 4]), 10.0, allow_error=True)
    dev.cmd("NSSHI", 10.0, allow_error=True)
    t0 = time.time()
    dev.cmd("AES-SUB", 240.0, allow_error=True)
    elapsed = time.time() - t0
    got = [dev.num(f"{i} SB@ .", 10.0) & 0xFF for i in range(16)]
    check("SubBytes+ShiftRows matches the reference", got == want, " ".join(f"{b:02x}" for b in got))
    print(f"        one phase = {elapsed:.2f} s wall (SPI byte-by-byte, includes the reply)")
    print(f"  {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
