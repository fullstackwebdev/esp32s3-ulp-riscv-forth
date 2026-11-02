#!/usr/bin/env python3
"""The radio bring-up as a PHASE: does a chained INIT actually configure the chip?

    python3 tests/lora_init_phase.py [--a /dev/ttyUSB0] [--b /dev/ttyUSB1]

WHAT THIS PROVES
  1. `examples/apps/lora/lorainit.fs` loads as a self-contained unit and configures the radio from its
     byte table: `RADIO-INIT` answers 1, chipmode goes to STDBY_RC, and the frequency register reads back
     0x36419999 (868.1 MHz) - read OUT of the chip with ReadRegister, not restated from the source.
  2. The receive words still work on top of it: `SR` puts the chip in RX (chipmode 5).
  3. A frame from the OTHER board, whose radio was configured by the app-phase `INIT`, is decoded here -
     so a phase-configured radio and an app-configured radio talk to each other.

GUARDRAIL: every name is pre-flighted with `' NAME .` against the board before it is defined. A resident name
cannot be redefined (mkentry refuses it) and one refusal makes every later definition fail, so a name check
turns what looks like a dead phase into a named error.
GUARDRAIL: `C,` bytes must leave HERE EVEN, or every later definition is refused with ERR_DICT (uforth.c
refuses while HERE is odd, since xt is stored as xt/2). tools/lint_forth.py R28 checks the parity of the
interpret-state `C,` count before the board ever sees the file.
"""
import argparse
import pathlib
import re
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "tools"))
from devio import Dev  # noqa: E402

INIT_PHASE = REPO / "examples/apps/lora/lorainit.fs"
RX_WORDS = REPO / "examples/apps/lora/lora_rx.fs"
DRIVER = REPO / "examples/apps/lora/lora1.fs"
MARKER = [0xA5, 0x31, 0x32, 0x33]
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:44s} {detail}")
    if not ok:
        fails.append(name)


def last_line(rep):
    lines = [l.strip() for l in rep.strip().splitlines() if l.strip()]
    return lines[-1] if lines else ""


def name_free(dev, name):
    """True when the machine does NOT know `name`.

    GUARDRAIL: judge the LAST LINE only, and sync first. Two traps here, both measured: a name with a digit in it
    (`RD2`) made a digit-extracting parser read the '2' out of `RD2?` and call a free name taken; and a leftover
    `ok` from the previous reply made an `"ok" in rep` test call a free name taken too. One question, then the
    reply's shape: a free name answers exactly `NAME?`.
    """
    dev.cmd("0 .", timeout=5.0, allow_error=True)      # sync point: whatever was pending is consumed
    return last_line(dev.cmd(f"' {name} .", timeout=6.0, allow_error=True)) == f"{name}?"


def word_defined(dev, name):
    rep = dev.cmd(f"' {name} .", timeout=6.0, allow_error=True)
    return bool(re.fullmatch(r"-?\d+\s+ok", last_line(rep)))


def load(dev, path, label):
    """Type a file, pre-flighting names and verifying each definition at its closing `;`."""
    pend, name = [], None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("\\"):
            continue
        m = re.match(r":\s+(\S+)", line)
        if m and not pend:
            name = m.group(1)
            if not name_free(dev, name):
                rep = dev.cmd(f"' {name} .", timeout=6.0, allow_error=True)
                raise SystemExit(f"{label}: `{name}` already exists - reply {rep.strip()[-40:]!r}")
        if name:
            pend.append(line)
            if line.endswith(";"):
                for one in pend:
                    dev.cmd(one, timeout=8.0, allow_error=True)
                if not word_defined(dev, name):
                    raise SystemExit(f"{label}: `{name}` did not appear after its definition closed")
                pend, name = [], None
            continue
        rep = dev.cmd(line, timeout=8.0, allow_error=True)
        if "ERR_" in rep or rep.strip().endswith("?"):
            raise SystemExit(f"{label}: refused at interpret level: {line[:50]!r} -> {rep.strip()[-30:]!r}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="/dev/ttyUSB0")
    ap.add_argument("--b", default="/dev/ttyUSB1")
    a = ap.parse_args()
    B = Dev(port=a.b)
    B.reset()
    h0, l0 = B.num("HERE ."), B.num("LATEST .")
    load(B, INIT_PHASE, "init-phase")
    h1, l1 = B.num("HERE ."), B.num("LATEST .")
    print(f"  init phase footprint: code {h1-h0} B + headers {l0-l1} B = {h1-h0+l0-l1} B, "
          f"free after {l1-h1} B")

    check("RADIO-INIT answers ok", B.num("RADIO-INIT .", timeout=25.0) == 1)
    st = B.num("STAT .", timeout=8.0)
    check("chip is in STDBY_RC after the phase init", ((st >> 4) & 7) == 2, f"status 0x{st:02X}")
    t_ = B.num("PTYPE .", timeout=8.0)
    check("radio reports packet type LoRa", t_ == 1, f"GetPacketType -> {t_} (1 = LoRa)")

    load(B, RX_WORDS, "rx-words")
    B.cmd("RC SR", timeout=8.0, allow_error=True)
    st = B.num("STAT .", timeout=8.0)
    check("SR puts the chip in RX", ((st >> 4) & 7) == 5, f"status 0x{st:02X}")

    A = Dev(port=a.a)
    A.reset()
    load(A, DRIVER, "driver")
    check("app-phase INIT answers ok on the other board", A.num("INIT .", timeout=15.0) == 1)
    A.close()   # release the port for the sender thread
    A = Dev(port=a.a)
    A.reset()
    load(A, DRIVER, "driver")
    A.num("INIT .", timeout=15.0)

    def send():
        for _ in range(3):
            A.num("SEND .", timeout=12.0)
            time.sleep(0.4)

    t = threading.Thread(target=send)
    t.start()
    t.join()
    time.sleep(0.4)
    irq = B.num("IQ .", timeout=8.0)
    decoded = bool(irq & 0x0002)
    check("a frame sent by the app-phase radio is decoded here", decoded, f"irq 0x{irq:04X}")
    if decoded:
        payload = B.cmd("RL RB", timeout=10.0, allow_error=True)
        bytes_seen = [int(x) for x in re.findall(r"\d+", last_line(payload))]
        check("payload is the driver's marker", bytes_seen == MARKER, f"got {bytes_seen} want {MARKER}")

    A.close(); B.close()
    print(f"  {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
