#!/usr/bin/env python3
"""AES-128 in Forth, checked against FIPS-197 on the board.

    python3 tests/lora_aes.py [--port /dev/ttyUSB1]

Two vectors, both from FIPS-197 (Appendix A.1 for the schedule, B.1 for the block):
  key        000102030405060708090a0b0c0d0e0f
  w[4..7]    a0fafe17 88542cb1 23a33939 2a6c7605
  plaintext  00112233445566778899aabbccddeeff
  ciphertext 69c4e0d86a7b0430d8cdb78070b4c55a
CTR is checked against the same keystream by encrypting the plaintext twice (AES-CTR is its own inverse).

GUARDRAIL: the expected values are FIPS-197's, not derived from this implementation - a test written from its own
output proves only that the code is deterministic.
"""
import argparse
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "tools"))
from devio import Dev  # noqa: E402

AES = REPO / "examples/apps/lora/lora_aes.fs"
KEYSCHED = REPO / "examples/apps/lora/lora_keysched.fs"
KEY = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15]
PLAIN = [0x00,0x11,0x22,0x33,0x44,0x55,0x66,0x77,0x88,0x99,0xaa,0xbb,0xcc,0xdd,0xee,0xff]
WANT_W4 = [0xa0,0xfa,0xfe,0x17,0x88,0x54,0x2c,0xb1,0x23,0xa3,0x39,0x39,0x2a,0x6c,0x76,0x05]
WANT_CT = [0x69,0xc4,0xe0,0xd8,0x6a,0x7b,0x04,0x30,0xd8,0xcd,0xb7,0x80,0x70,0xb4,0xc5,0x5a]
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:46s} {detail}")
    if not ok:
        fails.append(name)


def load(dev, path):
    pend, name = [], None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("\\"):
            continue
        m = re.match(r":\s+(\S+)", line)
        if m and not pend:
            name = m.group(1)
            dev.cmd("0 .", timeout=5.0, allow_error=True)
            rep = dev.cmd(f"' {name} .", timeout=6.0, allow_error=True)
            last = [s.strip() for s in rep.strip().splitlines() if s.strip()][-1]
            if last != f"{name}?":
                raise SystemExit(f"`{name}` already exists (reply {last!r})")
        if name:
            pend.append(line)
            if line.endswith(";"):
                for one in pend:
                    dev.cmd(one, timeout=8.0, allow_error=True)
                rep = dev.cmd(f"' {name} .", timeout=6.0, allow_error=True)
                if not re.fullmatch(r"-?\d+\s+ok", [s.strip() for s in rep.strip().splitlines() if s.strip()][-1]):
                    raise SystemExit(f"`{name}` did not appear after its definition closed")
                pend, name = [], None
            continue
        dev.cmd(line, timeout=8.0, allow_error=True)


def poke_bytes(dev, base, values):
    """Write bytes with C! and print nothing."""
    for i, v in enumerate(values):
        addr = f"{base} {i} + " if i else f"{base} "
        dev.cmd(f"{v} {addr}C!", timeout=5.0, allow_error=True)


def peek_bytes(dev, base, n):
    """Read n bytes as numbers with separators (this console prints numbers with no trailing space)."""
    out = []
    for i in range(n):
        addr = f"{base} {i} + " if i else f"{base} "
        rep = dev.cmd(f"{addr}C@ .", timeout=5.0, allow_error=True)
        nums = re.findall(r"\d+", [s.strip() for s in rep.strip().splitlines() if s.strip()][-1])
        out.append(int(nums[-1]) if nums else None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB1")
    a = ap.parse_args()
    from lintgate import require_clean
    require_clean([AES, KEYSCHED], "--repl", where="aes")
    d = Dev(port=a.port)
    d.reset()
    h0, l0 = d.num("HERE ."), d.num("LATEST .")
    load(d, AES)
    h1, l1 = d.num("HERE ."), d.num("LATEST .")
    print(f"  aes footprint: code {h1-h0} B + headers {l0-l1} B = {h1-h0+l0-l1} B, free after {l1-h1} B")

    poke_bytes(d, "BUF", KEY)
    d.cmd("AKEY", timeout=20.0, allow_error=True)
    got_w4 = peek_bytes(d, "WZ", 16) if False else peek_bytes(d, "WZ", 16)
    check("key schedule matches FIPS-197 w[4..7]", got_w4 == WANT_W4, f"got {[hex(x) for x in got_w4]}")

    poke_bytes(d, "ST", PLAIN)
    d.cmd("AESB", timeout=20.0, allow_error=True)
    got_ct = peek_bytes(d, "ST", 16)
    check("block encrypt matches FIPS-197 ciphertext", got_ct == WANT_CT, f"got {[hex(x) for x in got_ct]}")

    poke_bytes(d, "BUF", PLAIN)
    d.cmd("AESB", timeout=20.0, allow_error=True)     # ST now holds E(PLAIN); CTR keystream is the same
    poke_bytes(d, "BUF", PLAIN)
    d.cmd("16 LEN !", timeout=6.0, allow_error=True)
    d.cmd("CPYN AESB CXOR", timeout=25.0, allow_error=True)
    got = peek_bytes(d, "BUF", 16)
    check("CTR(plaintext) equals the ciphertext", got == WANT_CT, f"got {[hex(x) for x in got]}")
    d.cmd("CPYN AESB CXOR", timeout=25.0, allow_error=True)
    back = peek_bytes(d, "BUF", 16)
    check("CTR is its own inverse", back == PLAIN, f"got {[hex(x) for x in back]}")

    print(f"  {len(fails)} failure(s)")
    d.close()
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
