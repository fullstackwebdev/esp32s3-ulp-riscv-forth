#!/usr/bin/env python3
"""Decode the host engine's `[gpio pin=level]` trace into SX126x SPI transactions, and check the driver.

    python3 probe/repl/tests/lora_spi.py

WHY THIS EXISTS. `examples/apps/lora/lora1.fs` is a bit-banged SPI driver written in Forth. On the chip it is verified by
the radio answering; on the host there is no radio, but there IS the engine's own pin trace (pl_hw op 1 prints
`[gpio pin=level]` for every write, and op 0 reads the simulated pin word). That trace is enough to reconstruct the wire:
NSS frames the transactions, SCK rising edges sample MOSI, and the byte sequence is what the SX1262 would have received.

So this test asserts the thing that matters and cannot be faked: **the exact command byte stream the driver puts on the
wire**. It is the same stream the C driver in probe/lora produces on real hardware (docs/29), so agreement here means the
Forth translation is faithful - and it is checked with no board and no simulated chip model, just the pins.

GUARDRAIL: decode from transitions, not from a per-bit event count. The trace prints a pin write only when the VALUE
changes for MOSI (the driver writes 0 or 1 unconditionally, so it does print every time) but SCK always toggles, and any
later change to write-when-changed would silently shift every byte if the decoder counted events instead of edges.
"""
import pathlib
import re
import subprocess
import sys

PROBE = pathlib.Path(__file__).resolve().parents[1]
ROOT = PROBE.parents[1]
DRIVER = ROOT / "examples" / "apps" / "lora" / "lora1.fs"
HOST_APP = PROBE / "artifacts" / "host_app"
EXPAND = PROBE / "artifacts" / "expand"
WORK = PROBE / "artifacts" / "work"

PIN_NSS, PIN_SCK, PIN_MOSI, PIN_MISO = 8, 9, 10, 11
EVENT = re.compile(rb"\[gpio (\d+)=(\d)\]")


def run(entry, timeout=120.0):
    """Run the driver on the host engine with `entry` as the program, returning (expanded stdout, stderr)."""
    WORK.mkdir(parents=True, exist_ok=True)
    e = WORK / "lora_entry.fs"
    e.write_text(entry + "\n")
    out = subprocess.run([str(HOST_APP), str(DRIVER), str(e)], capture_output=True, timeout=timeout)
    raw = subprocess.run([str(EXPAND)], input=out.stdout, capture_output=True, timeout=60.0)
    return raw.stdout, out.stderr


def transactions(stream):
    """Rebuild the SPI byte stream as a list of transactions, one per NSS-low window."""
    pins = {PIN_NSS: 1, PIN_SCK: 0, PIN_MOSI: 0, PIN_MISO: 0}
    txns, cur = [], None
    bits, nbits = 0, 0
    bit_in = 0
    for m in EVENT.finditer(stream):
        pin, lvl = int(m.group(1)), int(m.group(2))
        prev = pins.get(pin)
        pins[pin] = lvl
        if pin == PIN_NSS:
            if lvl == 0 and prev == 1:                 # falling: a transaction begins
                cur = []
                bits, nbits = 0, 0
            elif lvl == 1 and prev == 0 and cur is not None:   # rising: it ends
                if nbits:                              # a partial byte is a wire error, report it
                    cur.append(("partial", nbits))
                txns.append(cur)
                cur = None
        elif pin == PIN_SCK and lvl == 1 and prev == 0 and cur is not None:
            # rising edge: sample MOSI (out) and MISO (in) - mode 0
            bits = (bits << 1) | pins[PIN_MOSI]
            bit_in = (bit_in << 1) | pins[PIN_MISO]
            nbits += 1
            if nbits == 8:
                cur.append(bits)
                bits, nbits = 0, 0
    return txns


def bytes_of(txns):
    return [b for t in txns for b in t if isinstance(b, int)]


# The cold-init command sequence, as the C driver on the hardware emits it (opcode, payload bytes).
EXPECTED_INIT = [
    [0x80, 0x00],                          # SetStandby STDBY_RC
    [0x96, 0x01],                          # SetRegulatorMode DC-DC
    [0x97, 0x02, 0x00, 0x01, 0x40],        # SetDIO3AsTCXOCtrl 1.8 V, 5 ms
    [0x89, 0x7F],                          # Calibrate all blocks
    [0x9D, 0x01],                          # SetDIO2AsRFSwitch
    [0x8A, 0x01],                          # SetPacketType LoRa
    [0x86, 0x36, 0x41, 0x99, 0x99],        # SetRfFrequency 868.1 MHz
    [0x98, 0xD7, 0xDB],                    # CalibrateImage 863-870
    [0x95, 0x02, 0x02, 0x00, 0x01],        # SetPaConfig 14 dBm
    [0x8E, 0x0E, 0x04],                    # SetTxParams 14 dBm, 200 us
    [0x8F, 0x00, 0x00],                    # SetBufferBaseAddress
    [0x8B, 0x09, 0x04, 0x01, 0x00],        # SetModulationParams SF9 BW125 CR4/5
    # GUARDRAIL: 0x74 is not an SX126x command - this expectation used to encode that bug, so the suite demanded a
    # sync write the chip ignored. The real form is WriteRegister(0x0740) with the pair measured in sync.conf.
    [0x0D, 0x07, 0x40, 0x14, 0x24],                # WriteRegister 0x0740 = 0x14/0x24 (sync.conf, MEASURED)
    # GUARDRAIL: the antenna-mismatch workaround is a real write the driver performs (0x08D8 |= 0x1E, read back
    # 0x48 -> 0x5E). Omitting it from the expectation made the suite fail on correct behaviour.
    [0x0D, 0x08, 0xD8, 0x5E],                      # WriteRegister 0x08D8 = 0x5E (tx clamp)
    [0x8C, 0x00, 0x08, 0x00, 0x04, 0x01, 0x00],   # SetPacketParams, payload 4
    [0x08, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],   # SetDioIrqParams (all sources; see sx126x_min.c)
]


EXPECTED_TX_HEAD = [0x0E, 0x00]              # WriteBuffer, offset 0
EXPECTED_PAYLOAD = [0xA5, 0x31, 0x32, 0x33]   # the driver now sends 4 bytes: 20 did not fit the window
EXPECTED_CLEAR_IRQ = [0x02, 0xFF, 0xFF]      # ClearIrqStatus, both banks
EXPECTED_SETTX = [0x83, 0x0F, 0x00, 0x00]    # SetTx, timeout 0x0F0000 ticks


def check_send(fails):
    """The transmit path, up to and including SetTx.

    GUARDRAIL: this asserts what the host CAN know and names what it cannot. There is no SX1262 behind the simulated
    pins, so DIO1 never rises and LORA_SEND correctly returns 0 - a test that expected 1 here would be a test that lies
    about hardware it does not have. What is checked is the byte stream through SetTx, which is the whole write path.
    """
    out, _ = run("INIT DROP SEND .")
    txns = [t for t in transactions(out) if all(isinstance(b, int) for b in t)]
    print("send: %d transactions after init" % len(txns))
    tail = txns[len(EXPECTED_INIT):]
    want = [EXPECTED_TX_HEAD + EXPECTED_PAYLOAD, EXPECTED_CLEAR_IRQ, EXPECTED_SETTX]
    for i, (g, w) in enumerate(zip(tail, want)):
        if g != w:
            fails.append("send transaction %d: driver %s, expected %s"
                         % (i, " ".join("%02X" % b for b in g), " ".join("%02X" % b for b in w)))
    if len(tail) < len(want):
        fails.append("send: only %d transactions, expected %d" % (len(tail), len(want)))
    # the trailing "." must print 0: no radio answered DIO1 on the host
    plain = re.sub(rb"\[gpio \d+=\d\]", b"", out).replace(b"SRV blk0[0]=00 blk0[9]=09 blk3[9]=1e", b"")
    if b"0" not in plain:
        fails.append("SEND did not report the no-DIO1 outcome on the host")


def main():
    fails = []
    out, err = run("INIT .")
    text = out.decode("latin-1")
    if b"ERR_" in out:
        fails.append("engine reported an error: %r" % re.findall(r"ERR_[A-Z_]+", text))
    txns = transactions(out)
    got = bytes_of(txns)
    print("transactions: %d   bytes on the wire: %d" % (len(txns), len(got)))
    print("first bytes:", " ".join("%02X" % b for b in got[:24]))

    want = [b for cmd in EXPECTED_INIT for b in cmd]
    n = min(len(got), len(want))
    first_bad = next((i for i in range(n) if got[i] != want[i]), None)
    if first_bad is None and len(got) < len(want):
        first_bad = len(got)
    if first_bad is not None:
        fails.append("byte %d differs: driver 0x%02X, expected 0x%02X (context %s)"
                     % (first_bad,
                        got[first_bad] if first_bad < len(got) else -1,
                        want[first_bad],
                        " ".join("%02X" % b for b in got[max(0, first_bad - 4):first_bad + 4])))
    # GUARDRAIL: compare the SPLIT into commands, not just the flat byte list. A flat comparison passes when two
    # adjacent commands have their bytes shuffled across a boundary (e.g. a missing NSS toggle), which on hardware is a
    # completely different command - the same "looks right, is wrong" shape as F-141.
    got_frames = [t for t in txns if all(isinstance(b, int) for b in t)]
    for i, (g, w) in enumerate(zip(got_frames, EXPECTED_INIT)):
        if g != w:
            fails.append("transaction %d: driver %s, expected %s"
                         % (i, " ".join("%02X" % b for b in g), " ".join("%02X" % b for b in w)))
            break
    if len(got_frames) < len(EXPECTED_INIT):
        fails.append("only %d transactions, expected %d" % (len(got_frames), len(EXPECTED_INIT)))

    check_send(fails)

    for f in fails:
        print("FAIL " + f)
    print("all checks pass" if not fails else "%d failure(s)" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
