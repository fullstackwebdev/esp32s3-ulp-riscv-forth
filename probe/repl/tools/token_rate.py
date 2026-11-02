#!/usr/bin/env python3
"""Measure the ULP interpreter's token cost, then derive the LoRa SPI numbers from it.

This is the experiment docs/28 §6 asks for first: every figure in §4.4 ("6-10 tokens per bit at ~2-4 us per token
-> 30-80 kHz SCK") rests on a token cost nobody has measured. This script measures it and prints the derived table,
so docs/28 can carry measured numbers instead of a range.

    python3 probe/repl/tools/token_rate.py                  # autodetect the port
    python3 probe/repl/tools/token_rate.py --port /dev/ttyACM1 --iterations 200000

Method: three definitions with the SAME loop and a different number of tokens in the body (1, 3 and 5 `1-`). The
difference between their wall-clock times is pure per-token work, so the loop overhead cancels instead of being
attributed to a token. There is no cycle counter exposed to Forth, so the clock is the host's, around the whole
round trip - which is why the loops are long (hundreds of thousands of iterations) and why the same measurement is
run three times with the median taken.

Run this ONLY against our firmware (the Forth REPL on the ULP). It refuses to report numbers if the machine is not
answering as ours: a Meshtastic/IDF board on the other end would otherwise produce a plausible, wrong result.
"""
import argparse
import glob
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "probe" / "repl" / "tools"))

import cli  # noqa: E402

# The three bodies. Kept inside the REPL's 63-character line limit - the machine silently truncates longer lines
# (paid for once already: a 84-character FLOOD definition came back as `FLOOD?` and measured nothing).
# GUARDRAIL: keep every definition under 63 chars — the line reader truncates silently and the "measurement" then
# measures a definition that never compiled — count the characters before sending, and assert the reply is ` ok`.
BODIES = {
    "A1": (": A1 0 100000 BEGIN DUP WHILE 1- REPEAT DROP ;", 4),          # tokens/iteration
    "A2": (": A2 0 100000 BEGIN DUP WHILE 1- 1- 1- REPEAT DROP ;", 6),
    "A3": (": A3 0 100000 BEGIN DUP WHILE 1- 1- 1- 1- REPEAT DROP ;", 7),
}
LOOP_TOKENS = 100000


def find_port(explicit):
    if explicit:
        return explicit
    # our firmware's console is the S3's native USB-CDC; the CP210x bridge on the HELTEC board is a different board
    for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*"):
        ports = sorted(glob.glob(pattern))
        if ports:
            return ports[0]
    return None


def measure(d, line, repeats):
    """Time one definition end to end. Returns (define_s, [run_s, ...])."""
    for attempt in range(2):
        rep = d.cmd(line, timeout=20.0, allow_error=True)
        # GUARDRAIL: a definition that did not compile answers `NAME?`/`ERR_*`, not ` ok` — and then the run below
        # times an error message, which is fast and would look like a superb token cost — require ` ok` before timing.
        if " ok" in rep or attempt == 1:
            break
        time.sleep(0.2)
    if " ok" not in rep:
        raise SystemExit("definition did not compile: %r -> %r" % (line, rep.strip()[:120]))
    runs = []
    name = line.split()[1]
    for _ in range(repeats):
        t0 = time.monotonic()
        out = d.cmd(name, timeout=120.0, allow_error=True)
        runs.append(time.monotonic() - t0)
        if "ERR_" in out or "?" in out.replace(" ok", ""):
            raise SystemExit("running %s failed: %r" % (name, out.strip()[:120]))
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--iterations", type=int, default=LOOP_TOKENS,
                    help="must match the literal in BODIES; kept for documentation")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--assume-token-us", type=float, default=None,
                    help="skip the board and derive the SPI table from an assumed token cost")
    args = ap.parse_args()

    if args.iterations != LOOP_TOKENS:
        raise SystemExit("BODIES hard-code %d iterations; edit both or neither" % LOOP_TOKENS)

    if args.assume_token_us is not None:
        tok = args.assume_token_us
        print("assuming %.2f us/token (no board used)" % tok)
    else:
        port = find_port(args.port)
        if not port:
            raise SystemExit("no serial port found: plug the App Store board in, or pass --port")
        print("port %s" % port)
        d = cli.connect(port, 1.0)
        if d is None:
            # GUARDRAIL: connect() returns None for "not our firmware" (HERE 0, no dictionary) as well as for a dead
            # port - and a Meshtastic board answers on the SAME /dev/ttyUSB* the S3 used. Never fall through to a
            # measurement here; the numbers would be of someone else's firmware.
            raise SystemExit("no Forth REPL answered (%s) - refusing to measure. Is this our board?" % port)
        try:
            times = {}
            for name, (line, toks) in BODIES.items():
                runs = measure(d, line, args.repeats)
                times[name] = statistics.median(runs)
                print("  %s  %d tokens/iter  median %.3f s  (runs %s)"
                      % (name, toks, times[name], ", ".join("%.3f" % r for r in runs)))
        finally:
            d.close()

        # per-token cost from the pairwise differences: overhead cancels
        pairs = [("A1", "A2"), ("A2", "A3"), ("A1", "A3")]
        est = []
        for a, b in pairs:
            d_tok = BODIES[b][1] - BODIES[a][1]
            est.append((times[b] - times[a]) / (d_tok * LOOP_TOKENS) * 1e6)
        tok = statistics.median(est)
        print("  per-token estimates: %s us -> median %.3f us" % (", ".join("%.2f" % e for e in est), tok))
        if tok <= 0:
            raise SystemExit("non-positive token cost (%.3f us) - the loops did not take the expected time" % tok)

    # ---- derived: the LoRa bit loop, per docs/28 §4 ------------------------------------------------
    print("\nderived (docs/28 §4.4), at %.3f us/token:" % tok)
    print("  %-38s %10s %10s %10s" % ("shape", "us/byte", "KB/s", "SCK kHz"))
    # GUARDRAIL: units, twice over. bytes/s = 1e6/us_byte so KB/s = 1e3/us_byte, and SCK kHz = 8 bits/byte * KB/s =
    # 8e3/us_byte - the first version printed 1000/(8*us_byte), which understated the clock 1000x and would have made
    # a 40 kHz bus look like 0.65 kHz, i.e. "Forth is hopeless" for arithmetic reasons rather than real ones.
    for label, tokens_per_byte in (
        ("pure Forth bit loop, 6 tokens/bit", 48),
        ("pure Forth bit loop, 8 tokens/bit", 64),
        ("pure Forth bit loop, 10 tokens/bit", 80),
    ):
        us_byte = tokens_per_byte * tok
        print("  %-38s %10.1f %10.2f %10.1f"
              % (label, us_byte, 1e3 / us_byte, 8e3 / us_byte))
    # The SPIX primitive's cost is NOT a token cost: it is ~8 bit-times of C, so it does not improve with the
    # interpreter. Model it at the forum-reported ~350 kHz (docs/27), not as "1 token per byte".
    us_byte = 8e6 / (350e3 * 8) * 8
    print("  %-38s %10.1f %10.2f %10.1f"
          % ("SPIX C primitive (350 kHz, forum)", us_byte, 1e3 / us_byte, 350.0))
    # GUARDRAIL: the SPI cost only matters against air time — a 20-byte packet at SF9/125 kHz is ~90 ms of air
    # (4.096 ms/symbol, 8 preamble + 14 payload symbols). Print the share so nobody optimises the bus and misses it.
    air_ms = 90.0
    for label, bytes_spi in (("warm TX path", 35), ("cold init", 140)):
        us = bytes_spi * 48 * tok          # 6 tokens/bit worst case
        print("  %-38s %10.1f ms %9.1f %% of a %.0f ms packet" % (label, us / 1000.0, 100.0 * us / 1000.0 / air_ms, air_ms))


if __name__ == "__main__":
    main()
