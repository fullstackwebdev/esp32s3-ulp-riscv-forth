#!/usr/bin/env python3
"""One hop at a time, judged against a host AES-128: finds WHICH chain phase is wrong.

    python3 tests/aes_chain_steps.py [--port /dev/ttyUSB0]

The chain runs (seed -> ark -> [sub -> sr -> mc -> ark] x 10 -> out), 43 hops, and the block came back wrong. A wrong
block says nothing about which of the four phases is wrong, so this walks the SAME hops the dispatcher walks and prints
the state after each one, comparing with the host's value for that stage. The SX1262 buffer survives an adopt (proven
by tests/lora_adopt.py), so the print phase can be adopted between hops without losing the state.
"""
import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parents[2]))    # the repo root, for cli.py
from devio import Dev                      # noqa: E402
import cli                                 # noqa: E402

V = json.load(open(HERE / "data" / "mesh_frame.json"))
SBOX = [
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
]


def xt(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else (a << 1) & 0xFF


def key_expand(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = xt(rcon)
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return w


def ark(s, w, r):
    return bytes(s[i] ^ w[4 * r + i // 4][i % 4] for i in range(16))


def sub(s):
    return bytes(SBOX[b] for b in s)


def sr(s):
    # src = 4*((col + row) & 3) + row, state index i = 4*col + row
    return bytes(s[4 * (((i // 4) + (i % 4)) & 3) + (i % 4)] for i in range(16))


def mc(s):
    out = bytearray(16)
    for c in range(4):
        a = [s[4 * c + r] for r in range(4)]
        t = a[0] ^ a[1] ^ a[2] ^ a[3]
        for r in range(4):
            out[4 * c + r] = a[r] ^ t ^ xt(a[r] ^ a[(r + 1) % 4])
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    a = ap.parse_args()
    key = bytes.fromhex(V["psk"])
    nonce = bytes.fromhex(V["nonce"])
    w = key_expand(key)
    dev = Dev(port=a.port)
    dev.reset()
    cli.appstore(dev, HERE.parents[2],
                 only=("aesseed", "aessub", "aessr", "aesmc", "aesark", "aesout"))

    def hop(desc):
        dev.cmd("0 NXT !", 6.0, allow_error=True)
        dev.cmd(f"{desc} PICKX EXECUTE", 120.0, allow_error=True)
        return dev.num("NXT @ .", 10.0)

    def show(tag, want):
        rep = dev.cmd("9 PICKX EXECUTE", 60.0, allow_error=True)
        nums = [int(x) for x in re.findall(r"\b\d{1,3}\b", rep.split("9 PICKX EXECUTE")[-1])]
        got = bytes(n & 0xFF for n in nums[1:17]) if len(nums) >= 17 else b""
        ok = got == want
        print(f"  {'PASS' if ok else 'FAIL'}  {tag:28s} got {got.hex()}")
        if not ok:
            print(f"        {'':28s} want {want.hex()}")
        return ok

    print("  stage by stage (host AES-128 vs the chain's own phases):")
    want = nonce
    req = hop(80)
    show("seed writes the nonce", want)
    want = ark(nonce, w, 0)
    req = hop(112)
    show("AddRoundKey round 0", want)
    fails = 0 if want == ark(nonce, w, 0) else 0
    # rounds 1..10, comparing after every hop
    for r in range(1, 11):
        for desc, fn, tag in ((88, sub, "SubBytes"), (96, sr, "ShiftRows"),
                              (104, (lambda s: mc(s)) if r < 10 else (lambda s: s), "MixColumns"),
                              (112, lambda s, r=r: ark(s, w, r), "AddRoundKey")):
            hop(desc)
            want = fn(want)
            if not show(f"{tag} round {r}", want):
                fails += 1
        if fails >= 2:
            print("  stopping after two failures")
            break
    print(f"  {fails} stage failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
