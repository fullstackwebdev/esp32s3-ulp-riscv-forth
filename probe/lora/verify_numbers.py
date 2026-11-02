#!/usr/bin/env python3
"""Check docs/29-lora-measurements.md against the console capture and the datasheet formula.

    python3 probe/lora/verify_numbers.py

Every figure the document states as measured must appear in probe/lora/results/console-2026-11-01.txt, and every figure it
states as derived must come out of the formula here. This exists because a document with a wrong number in it is worse
than no document (F-143/F-144: an instrument and an expectation both lied in the same week), and because re-reading prose
is not a check.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
CAP = (ROOT / "results" / "console-2026-11-01.txt").read_text()
DOC = (ROOT.parents[1] / "docs" / "29-lora-measurements.md").read_text()

fails = []


def need(name, cond):
    print(("OK   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# ---- values that must be in the capture -------------------------------------------------------------------------
for token in ("GetStatus reply 0x2a", "status 0x2c", "spi 971 cyc/B", "cal 175503 cyc/10ms",
              "ulp 2804 B", "cold 2", "cause 4", "pads 1"):
    need("capture contains %r" % token, token in CAP)

# ---- sleep sequence: tx_ok == wakes once warm, and five cycles are present ---------------------------------------
pairs = sorted({(int(l.split()[1]), int(l.split()[3]))
                for l in CAP.splitlines() if "wakes" in l and "tx_fail" in l})
need("capture has the warm-up sample (wakes 1, tx_ok 0)", (1, 0) in pairs)
need("tx_ok == wakes on every sample from wakes >= 6", all(w == t for w, t in pairs if w >= 6))
need("at least five deep-sleep cycles (six distinct wake counts)", len({w for w, _ in pairs}) >= 6)
need("no failed transmit anywhere in the capture", "tx_fail   1" not in CAP and "tx_fail  1" not in CAP)

# ---- derived numbers, recomputed ---------------------------------------------------------------------------------
tsym = 2 ** 9 / 125e3
preamble = (8 + 4.25) * tsym
payload_sym = 8 + (-(-(8 * 20 - 4 * 9 + 28 + 16) // (4 * 9))) * (1 + 4)
air_ms = (preamble + payload_sym * tsym) * 1e3
need("payload symbols == 33 (doc says 33)", payload_sym == 33)
need("air time == 185.34 ms (doc says 185.34)", abs(air_ms - 185.34) < 0.01)
need("doc states the 185.34 ms derived figure", "185.34" in DOC)
need("doc states the 195.8 ms measured figure", "195.8" in DOC)
need("agreement 105.6 % (doc says 105.6)", abs(195.8 / air_ms * 100 - 105.6) < 0.05)

# ---- SPI rate conversions, with the units named (F-145) -----------------------------------------------------------
cycles, clock = 971, 17.55e6
bytes_s = clock / cycles
need("SPI == 144.6 kHz SCK (doc says 144.6)", abs(bytes_s * 8 / 1e3 - 144.6) < 0.1)
need("SPI == 18.1 kB/s (doc says 18.1)", abs(bytes_s / 1e3 - 18.1) < 0.05)

# ---- the power table must be the script's output, not a retyped table ---------------------------------------------
sys.path.insert(0, str(ROOT))
import power_budget  # noqa: E402

for period, days_row in ((30, "287"), (60, "1.5 years"), (5, "49")):
    mah_h = power_budget.per_hour(period)
    days = 2000 / mah_h / 24
    if period == 60:
        need("60 s period -> ~1.5 years (doc says 1.5 years)", abs(days / 365 - 1.5) < 0.05)
    else:
        need("%d s period -> ~%s days (doc says %s)" % (period, days_row, days_row),
             abs(days - float(days_row)) < 1.0)

# ---- nothing stale -----------------------------------------------------------------------------------------------
need("no '~108 ms' air-time claim left", "108 ms" not in DOC.replace("a \"~108 ms\" expectation", ""))

print()
print("%d check(s) failed" % len(fails) if fails else "all checks pass")
sys.exit(1 if fails else 0)
