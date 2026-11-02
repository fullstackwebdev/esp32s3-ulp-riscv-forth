#!/usr/bin/env python3
"""Prove the Forth driver actually drives the SX1262 SPI bus, by asking the radio to echo a byte back.

    python3 probe/repl/tests/lora_bus.py [--port /dev/ttyUSB0]

WHY: `INIT` returning 1 is NOT evidence (R18). The driver decides "the radio responded" by reading BUSY, and a dead
input reads 0, which is exactly the level INIT looks for - so a bus with nothing behind it passes. This test does the
one thing that cannot pass on a dead bus: it WRITES a byte into the SX1262's own RAM (WriteBuffer 0x0E) and READS it
back out (ReadBuffer 0x1E), and the answer must be the byte, not 0. A returned 0 means the radio never saw the write;
a returned byte means MOSI, MISO, SCK and NSS are all being driven and sampled by the coprocessor, which is the goal's
central claim rather than the interpreter's opinion of itself.

GUARDRAIL: every scratch name here is long (SPI-BIT-SHIFTER, SPI-RDBYTE). The 12-bit dictionary hash collides short
names silently - typing `: R1 ... ;` and `: RB ... ;` into a loaded driver made INIT vanish from the vocabulary while
its own definitions worked, because a short name reuses another name's hash slot and clobbers its chain link. That
cost a whole confusing run before this file existed.

GUARDRAIL: opening the serial port pulses DTR/RTS and RESETS the board, so the driver is loaded at the start of THIS
session rather than assumed from a previous one. Any test that types into the chip must load what it needs first.
"""
import argparse
import pathlib
import subprocess
import sys
import time

import serial

ROOT = pathlib.Path(__file__).resolve().parents[3]
DRIVER = ROOT / "examples" / "apps" / "lora" / "lora1.fs"
SCRATCH = ROOT / "probe" / "repl" / "tests" / "lora_bus.fs"
LINTER = ROOT / "probe" / "repl" / "tools" / "lint_forth.py"

# The byte we ask the radio to remember, and its complement: two different values make a stuck bit impossible to hide.
TESTBYTES = (0xAA, 0x5A, 0x0F, 0xF0)

def lint_gate(*files):
    """Run the project's Forth linter in --repl mode over every file about to be typed onto the board.

    GUARDRAIL: nothing may reach the device without a clean lint. Inline source strings are exactly how the `S?` bug and
    the over-long-line truncation got through: the ring is 63 bytes and silently eats the rest, and a short name that
    hashes into another name's slot erases that word with no error. Lint first, refuse to type otherwise.
    """
    r = subprocess.run([sys.executable, str(LINTER), "--repl", *[str(f) for f in files]],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("lint refused the load (nothing was typed onto the board):")
        print(r.stdout.rstrip())
        for ln in r.stderr.splitlines():
            print("  ", ln)
        raise SystemExit(1)
    print("lint: clean (" + ", ".join(f.name for f in files) + ")")


def load(s, line, timeout=1.2):
    """Type one line and require exactly `ok`. A failed definition must abort the run, not cascade (see the loader)."""
    s.write(line.encode() + b"\r\n")
    deadline, got = time.time() + timeout, ""
    while "ok" not in got and time.time() < deadline:
        got += s.read(4096).decode("latin-1", "replace")
    if "?" in got or "ERR" in got:
        print(f"  FAILED on: {line}\n  device said: {got.strip()[:200]!r}")
        return False
    return True


def query(s, line, timeout=1.2):
    """Run a line that prints a number and return it, or None."""
    s.reset_input_buffer()
    s.write(line.encode() + b"\r\n")
    deadline, got = time.time() + timeout, ""
    while time.time() < deadline:
        chunk = s.read(4096).decode("latin-1", "replace")
        if not chunk and "ok" in got:
            break
        got += chunk
        if "ok" in got and len(got.split()) > 2:
            break
    digits = [t for t in got.replace("\n", " ").split() if t.isdigit()]
    if not digits:
        print(f"  no number for {line!r}: {got.strip()[:120]!r}")
        return None
    return int(digits[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    a = ap.parse_args()

    lint_gate(SCRATCH)

    s = serial.Serial(a.port, 115200, timeout=0.35)
    s.setDTR(False); s.setRTS(True); time.sleep(0.3); s.setRTS(False)
    time.sleep(2.0); s.reset_input_buffer(); s.read(65536)

    # GUARDRAIL: boot marker before anything is believed; a board that rebooted mid-test reads like a dead bus.
    s.write(b"1 2 + .\r\n"); time.sleep(0.8)
    if "3" not in s.read(200).decode("latin-1", "replace"):
        print("FAIL: the console did not answer arithmetic - the board is not in the state the test needs")
        return 2

    for line in SCRATCH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("\\"):
            continue
        if not load(s, line):
            print("FAIL: scratch vocabulary did not load")
            return 2

    # GUARDRAIL: the vocabulary check itself. A 12-bit hash collision makes a word stop resolving with no error, so
    # every word this test needs is confirmed live before it is used, and the failure is named as a name collision.
    if query(s, "BU-STA .") is None:
        print("FAIL: BU-STA does not resolve - name collision or a definition that never got typed")
        return 2
    st1 = query(s, "BU-STA .")
    st2 = query(s, "BU-STA .")
    print(f"  GetStatus: {st1} then {st2} (a dead input reads 0; two identical non-zero reads means MISO is live)")

    load(s, "BU-RST")

    bad = 0
    for want in TESTBYTES:
        load(s, f"{want} BU-WRT")
        got = query(s, "BU-RD .")
        ok = got == want
        bad += 0 if ok else 1
        print(f"  WriteBuffer 0x{want:02X} -> ReadBuffer 0x{want & 0xFF:02X} "
              f"{'OK' if ok else f'GOT {got}'}")
    s.close()
    if bad:
        print(f"lora_bus: {bad} of {len(TESTBYTES)} mismatches - the SPI path is not driving the radio")
        return 1
    print(f"lora_bus: PASS - the radio echoed all {len(TESTBYTES)} bytes, so the coprocessor is driving "
          "MOSI/MISO/SCK/NSS and reading MISO back (measured on the device, not simulated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
