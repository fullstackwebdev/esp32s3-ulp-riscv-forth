#!/usr/bin/env python3
"""The AES block through the PHASE CHAIN: does four adopted phases compute AES-128?

    python3 tests/lora_aes_chain.py [--port /dev/ttyUSB0]

WHY A CHAIN. The cipher is 1328 B and a phase window is 999 B, so it cannot be one phase (measured), and
SubBytes+ShiftRows together were 1045 B, so it cannot be three. It is four:

    76 AES-SUB  SubBytes          836 B
    84 AES-SR   ShiftRows         722 B
    92 AES-MC   MixColumns        ~960 B
   100 AES-ARK  AddRoundKey       896 B

The 16-byte state AND the round counter travel in the SX1262's own buffer (offset 224 and 223), the one memory
measured to survive an adopt. AES-ARK increments the round and chains back to AES-SUB while round < 11, and
AES-MC skips MixColumns on the last round.

WHAT IS COMPARED. The block encrypts the CTR counter block (the Meshtastic nonce) with the LongFast channel key,
and the result must equal `openssl enc -aes-128-ecb` of the same block - the value pinned in
tests/data/mesh_frame.json. That is the keystream a Meshtastic peer would XOR its payload with.

GUARDRAIL: the chain is run by the store's own dispatcher (`100 SWITCH`), not by a loop in this test: SWITCH adopts
each phase in turn exactly as a card would.
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
from devio import Dev          # noqa: E402
import cli                     # noqa: E402

EXPECT = json.load(open(HERE / "data" / "mesh_frame.json"))
PHASES = ("aesseed", "aessub", "aessr", "aesmc", "aesark", "aesout")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:48s} {detail}")
    if not ok:
        fails.append(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    a = ap.parse_args()

    dev = Dev(port=a.port)
    dev.reset()
    built = cli.appstore(dev, REPO, only=PHASES)
    if built is None:
        raise SystemExit("the store build refused - see the lines above")
    sizes = {n: i for n, _d, i in built}
    check("all four cipher phases fit 999 B", all(v <= 999 for v in sizes.values()),
          " ".join(f"{n}={v}" for n, v in sizes.items()))

    check("the seed phase is in the store", any(n == "aesseed" for n, _d, _i in built))
    t0 = time.time()
    rep = dev.cmd("72 SWITCH", 300.0, allow_error=True)
    elapsed = time.time() - t0
    errs = [l.strip() for l in rep.splitlines() if l.strip().endswith("?") or "ERR_" in l]
    check("the chain ran without a named error", not errs, f"{errs[:2]}")

    nums = [int(x) for x in re.findall(r"\b\d{1,3}\b", rep)][-16:]
    got = "".join(f"{n & 0xFF:02x}" for n in nums)
    check("AES-128 block matches openssl", got == EXPECT["keystream_block"],
          f"{got} want {EXPECT['keystream_block']}")
    print(f"        the whole block took {elapsed:.1f} s through the chain")
    print(f"  {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
