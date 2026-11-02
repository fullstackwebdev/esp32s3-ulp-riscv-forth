#!/usr/bin/env python3
"""Is the RADIO's own buffer usable as memory shared between phases?

    python3 tests/lora_scratch.py [--port /dev/ttyUSB0]

WHY THIS MATTERS. A store phase is REPLACED on every adopt, so its dictionary and its buffers vanish. A chain
that has to carry 16 bytes of AES state (or 176 B of round keys) therefore needs memory that is not in the
dictionary. The registry is resident and costs window bytes, and the image has ~1 B spare, so the registry
cannot grow. The SX1262 has 256 B of buffer that belongs to the RADIO, not to the coprocessor: if it survives a
dictionary swap, a chain can use it as scratch, and the cipher can be split across phases that each fit the
999 B window.

WHAT IS MEASURED HERE
  1. write a 16-byte pattern into the chip's buffer at offset 240 (above the payload area a 26 B frame uses),
  2. reset the ESP32 - which is the harshest possible dictionary swap, worse than an adopt,
  3. load a FRESH dictionary whose only words are the SPI primitives and ReadBuffer,
  4. read offset 240 back and compare.

A reset also drives the pad state, so this is a stricter test than an adopt; if the bytes survive it, they
survive a phase switch.

GUARDRAIL: the payload offset is 240, not 0, because the driver's frames start at 0 - a scratch area that
overlaps the frame would corrupt the very packet the chain is working on.
"""
import argparse
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "tools"))
from devio import Dev                      # noqa: E402
from lintgate import require_clean         # noqa: E402

INIT_PHASE = REPO / "examples/apps/lora/lorainit.fs"
RX_WORDS = REPO / "examples/apps/lora/lora_rx.fs"
PATTERN = [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88,
           0x99, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xF0, 0x0F]
OFFSET = 240
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:52s} {detail}")
    if not ok:
        fails.append(name)


def last_line(rep):
    lines = [l.strip() for l in rep.strip().splitlines() if l.strip()]
    return lines[-1] if lines else ""


def load(dev, path):
    """Type a file, verifying each definition when its `;` closes (a silent drop leaves no word behind)."""
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


def define(dev, lines, name):
    """Type a definition and REQUIRE the word to exist. GUARDRAIL: a typed line over 63 B is dropped by the input
    ring SILENTLY - the write and the reader in this test were both 76 B and neither existed, so the probe reported
    the buffer's leftovers as the answer. Never use a word this test did not confirm."""
    for line in lines:
        dev.cmd(line, 10.0, allow_error=True)
    rep = last_line(dev.cmd(f"' {name} .", 8.0, allow_error=True))
    if not re.fullmatch(r"-?\d+\s+ok", rep):
        raise SystemExit(f"`{name}` did not appear after its definition ({rep!r}) - a line was probably too long")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    a = ap.parse_args()
    require_clean([INIT_PHASE], "--repl", where="init-phase")
    require_clean([RX_WORDS], "--repl", where="rx-words", use=[INIT_PHASE])

    dev = Dev(port=a.port)
    dev.reset()
    load(dev, INIT_PHASE)
    check("radio configures", dev.num("RADIO-INIT .", 30.0) == 1)

    # write the pattern with WriteBuffer(0x0E): opcode, offset, bytes
    # GUARDRAIL: 16 bytes of `N >BYTE` on one line is 76 B and the ring drops it, so the write is spread over
    # several typed lines. NSS stays low between lines, so the chip sees ONE transaction.
    dev.cmd(f"NSSLO 14 >BYTE {OFFSET} >BYTE", 10.0, allow_error=True)
    for i in range(0, 16, 4):
        dev.cmd(" ".join(f"{b} >BYTE" for b in PATTERN[i:i + 4]), 10.0, allow_error=True)
    dev.cmd("NSSHI", 10.0, allow_error=True)
    back = [dev.num(f"{OFFSET + i} RB1 .", 8.0) if False else None for i in range(16)]
    # read it straight back in the SAME dictionary first: proves the write, not the survival
    # ReadBuffer(0x1E): opcode, offset, then a status byte (dropped) and the data
    RB1 = [": RB1 ( o -- b )", "  NSSLO 30 >BYTE >BYTE RD-BYTE DROP",
           "  RD-BYTE NSSHI ;"]
    define(dev, RB1, "RB1")
    same = [dev.num(f"{OFFSET + i} RB1 .", 8.0) & 0xFF for i in range(16)]
    check("pattern reads back in the SAME dictionary", same == PATTERN, " ".join(f"{b:02x}" for b in same))

    # ---- the actual question: reset the ESP32 (dictionary gone) and read the RADIO's memory ----
    dev.reset()
    check("dictionary really was replaced", dev.num("HERE .", 20.0) == 786, f"HERE {dev.num('HERE .', 20.0)}")
    load(dev, INIT_PHASE)                    # primitives only; RADIO-INIT is NOT called
    load(dev, RX_WORDS)
    define(dev, RB1, "RB1")
    got = [dev.num(f"{OFFSET + i} RB1 .", 8.0) & 0xFF for i in range(16)]
    check("16 bytes survive a full dictionary reset", got == PATTERN,
          " ".join(f"{b:02x}" for b in got))
    print(f"  {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
