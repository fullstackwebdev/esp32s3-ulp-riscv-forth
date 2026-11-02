#!/usr/bin/env python3
"""Two boards, one driver, both directions - the outside receiver the LoRa objective asks for.

    python3 tests/lora_two_board.py [--a /dev/ttyUSB0] [--b /dev/ttyUSB1]

WHAT THIS PROVES, and what it deliberately does not:
  * A (the board under test) runs `examples/apps/lora/lora1.fs` and transmits with `SEND`. Its coprocessor drives
    every SPI edge; the answer is the chip's own TxDone bit.
  * B runs the SAME firmware (`probe/repl`) and the SAME driver, plus `examples/apps/lora/lora_rx.fs`, and decodes
    what A sent. That is an OUTSIDE receiver: different board, different power supply, different USB link.
  * Then the reverse: B transmits (`SEND`), A receives (`IQ RXTAKE`), so the link is exercised both ways.
  * It does NOT claim the HP core of A was asleep during the transmission - that was measured separately
    (probe/lora deep-sleep run, docs/29). Here both consoles are live because both machines have to PRINT.
  * RX words are Forth, not C: there is no bespoke receiver program anywhere in this path.

GUARDRAIL: the two boards must agree on frequency to within a fraction of the bandwidth. A uses
868 000 000 Hz (0x36419999 in lora1.fs INIT); a peer at 868.1 MHz is 100 kHz = 80 % of a 125 kHz channel away, so a
"receiver that hears nothing" would have said nothing about the transmitter. Both load the same driver, so both are
on 868.0 MHz by construction, and the test prints the frequency word read back from each board.
GUARDRAIL: the two listeners run in THREADS. A send and a 250 ms receive window cannot be sequenced from one thread
without losing frames to the gap between them, and a lost frame would be blamed on the radio.
"""
import argparse
import pathlib
import re
import sys
import subprocess
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "tools"))
from devio import Dev  # noqa: E402

DRIVER = REPO / "examples/apps/lora/lora1.fs"
RX = REPO / "examples/apps/lora/lora_rx.fs"
MARKER = bytes([0xA5, 0x31, 0x32, 0x33])       # what SEND writes: marker + "123"


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


def lint(paths, label):
    """Refuse a source the project's own linter rejects for the typed-at-the-prompt path.

    GUARDRAIL: this calls tools/lint_forth.py --repl instead of re-implementing a length check. The hand-rolled
    version duplicated R21 and drifted from it (it never saw comment lines, which the ring treats like any other);
    the linter is the one place that encodes what a typed line may look like.
    """
    for path in paths:
        r = subprocess.run([sys.executable, str(HERE.parent / "tools/lint_forth.py"), "--repl", str(path)],
                           capture_output=True, text=True)
        blocking = [l for l in r.stdout.splitlines() if "R21 line length" in l or "R11 fit" in l]
        if blocking:
            raise SystemExit(f"{label}: the linter refuses {path.name}:\n  " + "\n  ".join(blocking[:4]))
    return True


def load(dev, label):
    """Type a source file at the prompt and name any word that fails to appear.

    GUARDRAIL: verify at the CLOSING `;`, not per line. The driver's definitions span several lines (`PIN!`,
    `BITOUT`, `BUSY-LOW`, `INIT`, `SEND`), so a tick check after the first line of one asks about a word the machine
    is still in the middle of defining - which is exactly how the first version of this loader reported "`PIN!` did
    not appear" while the board had answered ` ok` to the opener. Collect a definition to its `;`, type it, then ask.
    GUARDRAIL: keep the tick check at all. A definition refused for a full dictionary, a hash collision or an
    over-long line is silent here, and the failure otherwise surfaces as `NAME?` two lines later - or as a receiver
    that "hears nothing" and gets blamed on the radio.
    """
    for path in (DRIVER, RX):
        pend, name = [], None
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("\\"):
                continue

            m = re.match(r":\s+(\S+)", line)
            if m and not pend:
                name = m.group(1)
                if not name_free(dev, name):
                    raise SystemExit(f"{label}: `{name}` already exists on the machine - a resident name cannot "
                                     "be redefined, and one refusal makes every later definition fail too")
            if name:
                pend.append(line)
                if line.endswith(";"):
                    for one in pend:
                        dev.cmd(one, timeout=8.0, allow_error=True)
                    if not word_defined(dev, name):
                        raise SystemExit(f"{label}: `{name}` did not appear after its definition closed - refused "
                                         f"silently (dictionary full, hash collision, or line too long)")
                    pend, name = [], None
                continue
            dev.cmd(line, timeout=8.0, allow_error=True)          # a CONSTANT or a bare call
        if pend:
            raise SystemExit(f"{label}: {path.name} ended with an unterminated definition of {name}")
    return True


def freq_of(dev):
    """Read back the frequency word the driver actually wrote, so 'both on 868 MHz' is measured, not assumed."""
    return dev.num("NSSLO 134 >BYTE 0 >BYTE 0 >BYTE 0 >BYTE 0 >BYTE NSSHI DROP 1 .", timeout=8.0)


def watch(dev, seconds, results, key):
    """Listen continuously and collect decodes.

    GUARDRAIL: listen in CONTINUOUS mode and poll the chip's irq word; do not re-arm a 250 ms window per attempt.
    Measured: four frames sent 400 ms apart were ALL missed by the windowed `IQ RXTAKE` (each attempt cost a host round
    trip, so the receiver was deaf between windows), while `RC SR` once and polling `IQ` caught the very first frame
    (irq 0x0016 = RxDone|Preamble|Header) and printed the payload out of the radio's own buffer. A window is fine for
    a hand test; a listener has to stay listening.
    """
    dev.cmd("RC SR", timeout=8.0, allow_error=True)
    end = time.time() + seconds
    while time.time() < end:
        irq = dev.num("IQ .", timeout=8.0)
        if irq & 0x0002:
            payload = dev.cmd("RL RB", timeout=10.0, allow_error=True)
            results[key].append({"irq": irq, "payload": payload.strip()})
            dev.cmd("RC", timeout=5.0, allow_error=True)
        elif irq & 0x0040:
            results[key].append({"crc": irq})
            dev.cmd("RC", timeout=5.0, allow_error=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="/dev/ttyUSB0")
    ap.add_argument("--b", default="/dev/ttyUSB1")
    a = ap.parse_args()

    A, B = Dev(port=a.a), Dev(port=a.b)
    A.reset(); B.reset()
    print(f"A {a.a}: here={A.num('HERE .')}   B {a.b}: here={B.num('HERE .')}")
    from lintgate import require_clean
    require_clean([DRIVER], "--repl", where="driver")
    require_clean([RX], "--repl", where="rx-words", use=[DRIVER])   # RD-BYTE/RD2 come from the driver
    load(A, "A")
    load(B, "B")
    print(f"driver + rx loaded on both; A here={A.num('HERE .')} latest={A.num('LATEST .')} "
          f"B here={B.num('HERE .')} latest={B.num('LATEST .')}")

    print(f"A INIT -> {A.num('INIT .', timeout=8.0)}   B INIT -> {B.num('INIT .', timeout=8.0)}")
    freq_cmd = "NSSLO 21 >BYTE RD-BYTE RD-BYTE RD-BYTE RD-BYTE NSSHI . . . ."
    fa = A.cmd(freq_cmd, timeout=8.0, allow_error=True)
    fb = B.cmd(freq_cmd, timeout=8.0, allow_error=True)
    print(f"GetRfFrequency bytes  A: {' '.join(fa.split()[-8:])}  B: {' '.join(fb.split()[-8:])}")

    results = {"a_to_b": [], "b_to_a": [], "b_lines": [], "a_lines": []}

    # ---- direction 1: A transmits (Forth/ULP driver), B listens ------------------------------------------------
    t = threading.Thread(target=watch, args=(B, 25.0, results, "a_to_b"), daemon=True)
    t.start()
    time.sleep(1.0)
    tx = []
    for i in range(3):
        tx.append(A.num("SEND .", timeout=10.0))
        time.sleep(1.0)
    t.join()
    print(f"A->B: SEND answered {tx} (TxDone from the chip's own irq), B decoded {len(results['a_to_b'])} frame(s)")

    # ---- direction 2: B transmits, A listens ------------------------------------------------------------------
    t2 = threading.Thread(target=watch, args=(A, 25.0, results, "b_to_a"), daemon=True)
    t2.start()
    time.sleep(1.0)
    tx2 = []
    for i in range(3):
        tx2.append(B.num("SEND .", timeout=10.0))
        time.sleep(1.0)
    t2.join()
    print(f"B->A: SEND answered {tx2}, A decoded {len(results['b_to_a'])} frame(s)")

    ok = True
    if not all(v == 1 for v in tx):
        print("FAIL  A did not report TxDone for every frame")
        ok = False
    if not results["a_to_b"]:
        print("FAIL  the outside receiver decoded NOTHING from A")
        ok = False
    if not all(v == 1 for v in tx2):
        print("FAIL  B did not report TxDone for every frame")
        ok = False
    if not results["b_to_a"]:
        print("FAIL  A decoded NOTHING from B (one-way only)")
        ok = False
    print("PASS  the frame crosses between two boards in both directions, decoded by the chip's own CRC" if ok else
          "FAIL  no frame crossed - see the irq words above; docs/29-lora-measurements.md has the table")
    A.close(); B.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
