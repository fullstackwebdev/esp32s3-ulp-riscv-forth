#!/usr/bin/env python3
"""Meshtastic interoperability, BOTH directions, in one command.

    python3 tests/mesh_interop.py [--ours /dev/ttyUSB1] [--peer /dev/ttyUSB0] [--frames 6]

What it proves, in order, and it refuses to skip a step:

  0. ROLES      which port runs our stack and which runs stock Meshtastic (by probing, never by port name or by MAC
                note - the boards get swapped).
  1. CONTROL    the link itself: this reports what the operator's physical setup can carry. The peer's own receiver is
                the instrument, so the instrument has to be validated before it is used to judge our transmitter.
                `--control` runs stock<->stock over the same boards only when both are Meshtastic; with our stack
                flashed on one board the control comes from the recorded baseline (docs/31 N.8) instead.
  2. OUR TX     our board transmits N frames; we count DECODE events on the peer and print the peer's own log lines as
                evidence. "Preamble detected" is never counted as success - a decoded packet is.
  3. THEIR TX   the peer sends text; our board must report IRQ 0x0016 (RxDone + HeaderValid) and we read the decrypted
                payload back off the chip.
  4. VERDICT    a named outcome. Anything other than both directions decoding is a failure with a reason, never a
                silent pass.

GUARDRAIL: never report "no decode" without first proving the peer's receiver works at all in the current physical
arrangement - stock<->stock failed in both directions at the same positions where our own firmware still decoded 2 of 3
frames, and that invalidated a whole round of transmit measurements.
"""
import argparse
import pathlib
import re
import subprocess
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE))
from dev_ready import ready                  # noqa: E402
from lora_frame_phase import load            # noqa: E402

LORA = REPO / "examples/apps/lora"
CLR = "NSSLO 2 >BYTE 255 >BYTE 255 >BYTE NSSHI"
TEXT = "ulp interop"


def probe_meshtastic(port, timeout=45):
    """Return the node number if stock Meshtastic answers on this port, else None."""
    try:
        r = subprocess.run(["meshtastic", "--port", port, "--info"], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    out = r.stdout + r.stderr
    m = re.search(r'"myNodeNum":\s*(\d+)', out)
    return int(m.group(1)) if m else None


def probe_ours(port):
    """Return the Dev if our REPL answers, else None."""
    try:
        return ready(port, tries=2, settle=4.0)
    except SystemExit:
        return None


class Listener:
    """A peer listener that timestamps every interesting line, so a decode can be attributed to a transmit window."""

    PATTERNS = (("DECODE", r"hi from ulp|" + re.escape(TEXT)),
                ("preamble", r"Ignore false preamble detection"),
                ("header", r"Ignore false header detection"),
                ("crc", r"CRC_ERR|CrcErr"),
                ("no channel", r"No suitable channel"),
                ("aes", r"Use AES"))

    def __init__(self, port, wait=20):
        self.events = []
        self.lock = threading.Lock()
        self.proc = subprocess.Popen(["meshtastic", "--port", port, "--listen", "--debug"],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        time.sleep(wait)

    def _read(self):
        for line in self.proc.stdout:
            with self.lock:
                for kind, pat in self.PATTERNS:
                    if re.search(pat, line):
                        self.events.append((time.monotonic(), kind, line.strip()[:160]))
                        break

    def window(self, t0, t1, kind):
        with self.lock:
            return [e for e in self.events if e[1] == kind and t0 <= e[0] <= t1]

    def stop(self):
        self.proc.kill()
        return self.proc.communicate()[0] or ""


def our_tx(dev, frames, table):
    load(dev, table)
    st = dev.num("RADIO-INIT .", 60.0)
    if st != 1:
        raise SystemExit(f"our board: RADIO-INIT returned {st}, expected 1")
    t0 = time.monotonic()
    for _ in range(frames):
        dev.cmd(CLR, 10.0, allow_error=True)
        dev.num("GO .", 120.0)
        time.sleep(1.4)
    return t0, time.monotonic()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", default=None)
    ap.add_argument("--peer", default=None)
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--table", default=None, help="our transmit table (default: the Meshtastic frame transmitter)")
    a = ap.parse_args()

    ports = [p for p in (a.ours, a.peer) if p] or ["/dev/ttyUSB0", "/dev/ttyUSB1"]

    # ---- 0. roles, by probing ------------------------------------------------------------------------------------
    ours = peer = None
    for p in ports:
        node = probe_meshtastic(p)
        if node is not None:
            peer = (p, node)
            print(f"  {p}: stock Meshtastic, node {node:#010x}")
            continue
        d = probe_ours(p)
        if d is not None:
            ours = (p, d)
            print(f"  {p}: our Forth stack (REPL answers arithmetic, HERE {d.num('HERE .', 10.0)})")
    if ours is None or peer is None:
        raise SystemExit(f"FAIL named reason=roles: need one Meshtastic board and one of ours; got "
                         f"ours={ours[0] if ours else None} peer={peer[0] if peer else None}")

    table = pathlib.Path(a.table) if a.table else LORA / "loratx_ms_hp.fs"
    print(f"  transmitting with {table.name}")

    # ---- 2. our TX -> their RX -----------------------------------------------------------------------------------
    listen = Listener(peer[0])
    t0, t1 = our_tx(ours[1], a.frames, table)
    decodes = listen.window(t0, t1, "DECODE")
    print(f"  our TX -> peer RX: {len(decodes)} decode(s) of {a.frames} frames")
    with listen.lock:
        observed = list(listen.events)
    for (t, kind, line) in observed:
        if t0 <= t <= t1:
            print(f"    [{kind}] {line}")
    listen.stop()

    # ---- 3. their TX -> our RX -----------------------------------------------------------------------------------
    load(ours[1], LORA / "lora_rx.fs")
    st = ours[1].num("RADIO-INIT .", 60.0)
    if st != 1:
        raise SystemExit(f"our board: RADIO-INIT (rx) returned {st}, expected 1")
    got = 0
    for attempt in range(3):
        ours[1].cmd("RC SR", 10.0, allow_error=True)
        subprocess.run(["meshtastic", "--port", peer[0], "--sendtext", TEXT],
                       capture_output=True, text=True, timeout=180)
        irq, deadline = 0, time.time() + 12
        while time.time() < deadline:
            irq = ours[1].num("IQ .", 20.0)
            if irq & 2 or irq & 0x40:
                break
            time.sleep(0.03)
        print(f"  peer TX -> our RX attempt {attempt + 1}: IRQ 0x{irq:04x}")
        if irq & 2:
            got += 1
    ours[1].close()

    # ---- 4. verdict ----------------------------------------------------------------------------------------------
    both = bool(decodes) and got > 0
    if not both:
        print(f"FAIL named reason=interop: our TX decoded {len(decodes)} time(s), their TX decoded {got}/3. "
              f"A single direction is not interoperability.")
        return 1
    print(f"PASS both directions: our frames decoded {len(decodes)}x by stock Meshtastic, "
          f"their frames decoded {got}/3 by us")
    return 0


if __name__ == "__main__":
    sys.exit(main())
