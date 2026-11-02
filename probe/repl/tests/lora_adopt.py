#!/usr/bin/env python3
"""Does the SX1262's buffer survive a real ADOPT? The premise a cipher phase chain rests on.

    python3 tests/lora_adopt.py [--port /dev/ttyUSB0]

THE QUESTION. A store phase is REPLACED on every adopt: its dictionary, its words and its buffers are gone. A chain
that carries 16 B of AES state (or 176 B of round keys) between phases therefore needs memory that is not in the
dictionary. The registry is resident and costs window bytes (image has ~1 B free), so the only candidate is the
radio's own 256-byte buffer. Measured already: exact in one dictionary, destroyed by an ESP32 reset. This is the
adopt case, which a reset cannot answer.

HOW. `cli.appstore()` writes the resident dictionary, seals it, and uploads two probe phases through the store:
  scr1 (descriptor 64) writes 16 bytes to radio-buffer offset 240 and CHAINs to 68,
  scr2 (descriptor 68) is adopted into a FRESH dictionary, reads offset 240 and PRINTS the bytes.
Then `64 GO` adopts, exactly as a card would.

GUARDRAIL: the printed bytes are the answer, so nothing here reads a variable - a phase cannot own one (R16).
"""
import argparse
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(REPO))
from devio import Dev          # noqa: E402
import cli                     # noqa: E402

PATTERN = [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88,
           0x99, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xF0, 0x0F]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    a = ap.parse_args()

    dev = Dev(port=a.port)
    dev.reset()
    built = cli.appstore(dev, REPO, only=("scratch1", "scratch2"))
    if built is None:
        raise SystemExit("the store build refused - see the lines above")
    print("  store built; adopting descriptor 64 ...")
    rep = dev.cmd("64 GO", 60.0, allow_error=True)
    print(f"  raw reply: {rep.strip()[:200]!r}")
    nums = [int(x) for x in re.findall(r"\b\d{1,3}\b", rep)][-16:]
    got = [n & 0xFF for n in nums]
    ok = got == PATTERN
    print(f"  printed back: {' '.join(f'{b:02x}' for b in got)}")
    print(f"  {'PASS' if ok else 'FAIL'}  radio buffer survives an ADOPT "
          f"({'identical' if ok else 'differs from ' + ' '.join(f'{b:02x}' for b in PATTERN)})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
