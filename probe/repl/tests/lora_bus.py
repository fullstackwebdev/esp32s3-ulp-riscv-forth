#!/usr/bin/env python3
"""Ask the SX1262 to remember a byte and say it back, over the SPI pins driven by the COPROCESSOR running FORTH.

    python3 probe/repl/tests/lora_bus.py [--port /dev/ttyUSB0]

WHY: `INIT` returning 1 is NOT evidence (R18). INIT decides "the radio responded" by reading BUSY, and a dead input
reads 0, which is exactly the level INIT looks for. This test writes 0x80 into the radio's own RAM and then 0x00, and
reads the most significant bit back from the radio each time. Those two answers together are the only pair that can
distinguish: a floating or stuck MISO answers 0 twice, so the 1 is what proves MOSI/SCK/NSS moved; the following 0 is
what proves MISO is a real signal and not a wire sitting high.

WHAT IT DOES NOT PROVE: it says nothing about LoRa modulation or air time - see tools/lora_device.py and the TxDone
measurement for that. It is the bus-level gate, and it is the test that has to pass before any `SEND` failure can be
blamed on anything but the pins.

GUARDRAIL: nothing is typed onto the device unless tools/lint_forth.py --repl accepts every line first. Every rule
behind that came from a real dead end: a line over the ring is TRUNCATED rather than rejected, and a short name whose
12-bit hash lands on another name's slot silently erases that word (measured: `: R1 ... ;` and `: RB ... ;` typed over
a loaded driver made INIT stop resolving while its other words kept working).

GUARDRAIL: opening the serial port pulses DTR/RTS and RESETS the board, so the driver is loaded in THIS session rather
than assumed from an earlier one. A test that types into the chip must load what it needs or say so.
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

# (payload written, MSB expected back). Two complementary patterns, so neither a stuck-low nor a stuck-high MISO
# can survive the test.
PATTERNS = ((0x80, 1), (0x00, 0), (0x81, 1), (0x01, 0))


def lint_gate(*files):
    """Refuse to touch the device until the linter has accepted every line that is about to be typed."""
    r = subprocess.run([sys.executable, str(LINTER), "--repl", *[str(f) for f in files]],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("lint refused the load (nothing was typed onto the board):")
        print(r.stdout.rstrip())
        for ln in r.stderr.splitlines():
            print("  ", ln)
        raise SystemExit(1)
    print("lint: clean (" + ", ".join(f.name for f in files) + ")")


def load(s, line, timeout=1.5):
    """Type one line and require `ok` with no error tag. A failed definition aborts rather than cascading."""
    s.write(line.encode() + b"\r\n")
    deadline, got = time.time() + timeout, ""
    while time.time() < deadline:
        got += s.read(4096).decode("latin-1", "replace")
        if "ok" in got:
            break
    if "ERR" in got or "?" in got:
        print(f"  FAILED on: {line}\n  device said: {got.strip()[:200]!r}")
        return False
    return True


def query(s, line, timeout=1.5):
    """Run a line that prints one number and return it, or None if nothing numeric came back."""
    s.reset_input_buffer()
    s.write(line.encode() + b"\r\n")
    deadline, got = time.time() + timeout, ""
    while time.time() < deadline:
        chunk = s.read(4096).decode("latin-1", "replace")
        got += chunk
        if "ok" in got and any(t.isdigit() for t in got.split()):
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

    lint_gate(DRIVER, SCRATCH)

    s = serial.Serial(a.port, 115200, timeout=0.35)
    s.setDTR(False); s.setRTS(True); time.sleep(0.3); s.setRTS(False)
    time.sleep(2.0); s.reset_input_buffer(); s.read(65536)

    # GUARDRAIL: arithmetic first, so a board that rebooted or never booted is named as itself rather than as a dead bus.
    s.write(b"1 2 + .\r\n"); time.sleep(0.8)
    if "3" not in s.read(200).decode("latin-1", "replace"):
        print("FAIL: the console did not answer arithmetic - the board is not in the state this test needs")
        return 2

    for f in (DRIVER, SCRATCH):
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("\\"):
                continue
            if not load(s, line):
                print(f"FAIL: {f.name} did not load")
                return 2

    if query(s, "INIT .") != 1:
        print("FAIL: INIT did not report success")
        return 2

    bad = 0
    for payload, want in PATTERNS:
        # The driver's own words do the transaction: 0x0E is WriteBuffer, then the offset, then the byte.
        if not load(s, f"[ 14 >B 0 >B {payload} >B ]"):
            print("FAIL: the WriteBuffer transaction was rejected")
            return 2
        got = query(s, "RAMREADBIT .")
        ok = got == want
        bad += 0 if ok else 1
        print(f"  radio RAM 0x{payload:02X} -> MSB {got} (want {want}) {'OK' if ok else 'MISMATCH'}")

    s.close()
    if bad:
        print(f"lora_bus: FAIL - {bad} of {len(PATTERNS)} answers wrong. 99 means BUSY never cleared (the radio is "
              "not listening); 0 where 1 was due means the coprocessor's write did not reach MOSI.")
        return 1
    print(f"lora_bus: PASS - the radio echoed {len(PATTERNS)} complementary patterns through the coprocessor's own "
          "pins, so MOSI, SCK, NSS and MISO are driven and sampled by the ULP under Forth control")
    return 0


if __name__ == "__main__":
    sys.exit(main())
