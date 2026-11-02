#!/usr/bin/env python3
"""Type the Forth LoRa driver into the DEVICE REPL and transmit a packet. The end-to-end test.

    python3 probe/repl/tools/lora_device.py [--port /dev/ttyUSB0] [--dry]

WHY: the host test (tests/lora_spi.py) proves the wire bytes; only the board can prove the packet. This sends
examples/apps/lora/lora1.fs line by line into the chip's REPL - the device TIB is 96 characters, so every line must be
shorter than that, which the file already satisfies - then runs LORA_PINS, LORA_INIT and LORA_SEND.

GUARDRAIL: one line at a time, waiting for `ok` between lines. The chip's input ring is 64 B, so a burst of source text
overflows it and the interpreter silently sees a truncated line; the failure then looks like a compile error in a
definition the operator can see is correct.

GUARDRAIL: a line that answers anything other than `ok` aborts with that answer printed. Carrying on after a failed
definition produces a cascade of `?` on every later word that uses it, and the real cause scrolls away.
"""
import argparse
import pathlib
import sys
import time

import serial

ROOT = pathlib.Path(__file__).resolve().parents[3]
DRIVER = ROOT / "examples" / "apps" / "lora" / "lora1.fs"


def read_until(ser, token=b"ok", timeout=8.0):
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            if token in buf:
                return buf, True
    return buf, False


def send_line(ser, line, timeout=8.0):
    """Send one line and wait for ITS answer.

    GUARDRAIL: the chip prints `ok` TWICE per line (once as the line's result, once as the next prompt), so waiting for
    the first `ok` returns the PREVIOUS line's prompt. That pipelined the whole file into the 64 B input ring, which
    truncated lines and made perfectly good definitions fail with `NAME?` - and the tool reported the failure one line
    late, on a line that was fine. Wait for the echo of THIS line, then for an `ok` after it.
    """
    ser.write(line.encode() + b"\r\n")
    ser.flush()
    echo = line.encode()
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        chunk = ser.read(256)
        if not chunk:
            continue
        buf += chunk
        at = buf.find(echo)
        if at >= 0 and b"ok" in buf[at:]:
            return buf[at:], True
    return buf, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--dry", action="store_true", help="print the lines that would be sent")
    args = ap.parse_args()

    lines = [l for l in DRIVER.read_text().splitlines()]
    # GUARDRAIL: the DEVICE input ring holds 63 B per line, not the host TIB's 95. Everything longer is refused
    # with "line too long" and never runs, so a definition silently never exists and the failure surfaces later as
    # NAME? on a line that is fine (measured; it cost an hour).
    too_long = [(i + 1, len(l.encode())) for i, l in enumerate(lines) if len(l.encode()) > 63]
    if too_long:
        raise SystemExit("line(s) longer than the device input ring (63 B): %s" % too_long)
    if args.dry:
        for l in lines:
            print(l)
        return 0

    ser = serial.Serial(args.port, 115200, timeout=0.2)
    time.sleep(0.3)
    ser.reset_input_buffer()
    # the board answers a bare newline with `ok`; if it does not, this is not our REPL and nothing below is meaningful
    ser.write(b"\r\n")
    hello, ok = read_until(ser, timeout=3.0)
    if not ok:
        raise SystemExit("no `ok` from %s - is our Forth firmware flashed? got %r" % (args.port, hello[-80:]))

    failed = 0
    for i, line in enumerate(lines, 1):
        out, ok = send_line(ser, line)
        if not ok:
            print("FAIL line %d: %r" % (i, line[:70]))
            print("     answer: %r" % out[-160:])
            failed += 1
            break
        text = out.decode("latin-1")
        # GUARDRAIL: a comment can legitimately contain "ERR_STACK" (this file explains it), and the echo of a comment is
        # not an error. Only judge result text, and never judge a line that is itself a comment.
        is_comment = line.lstrip()[:1] in ("\\", "(")
        verdict = text.split("ok")[0]
        if not is_comment and ("?" in verdict or "ERR_" in verdict):
            print("FAIL line %d: %r" % (i, line[:70]))
            print("     answer: %r" % text[-160:])
            failed += 1
            break

    if failed:
        ser.close()
        return 1

    for step in ("HERE .", "LORA_PINS 88 .", "LORA_INIT .", "LORA_SEND .", "HERE ."):
        out, ok = send_line(ser, step, timeout=20.0)
        print("%-16s -> %s" % (step, out.decode("latin-1").strip().replace("\r\n", " | ")[-120:]))
        if not ok:
            print("FAIL %s timed out" % step)
            failed += 1
            break

    ser.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
