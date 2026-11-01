#!/usr/bin/env python3
"""ms_clock.py — does `MS` actually wait? Two points, plus a baseline.

The bug this exists for: `MS` was `pl_hw(3, POP(), 0)` returning the wake count, i.e. **no sleep at all** — twenty
`200 MS` measured at 0.05 s. It is the reason a demo "paced" at 200 ms drew ~267 frames/s, walked its counter past 790
in four seconds, and put its own digit into the console's message-code space (F-124). A sleep that does not sleep is
invisible unless something measures wall time, and nothing did.

Method: time a REPL round trip. A line that does nothing costs the round trip (baseline); `100 MS` must cost the round
trip plus 100 ms, and `300 MS` plus 300 ms. Two points, because one point cannot tell "sleeps 100 ms" from "sleeps 200
ms", and the delta between them is free of the round-trip constant.

GUARDRAIL: measure the baseline in the SAME session and subtract it. The round trip is ~40 ms over USB but it drifts
with console load, and a fixed allowance turned a working clock into a failure on a busy host.
GUARDRAIL: the pass band is wide on purpose (+/-25 %) because the constant is the core clock, measured at 19.0 MHz
+/- 1.5 % (P05), and because a host timer is not a stopwatch. A clock that is wrong by 25 % is a bug; one that is
wrong by 3 % is the board.
"""
import os, sys, time, pathlib

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "probe" / "repl" / "tools"))

PORT = os.environ.get("PORT_DEV", "/dev/ttyACM1")


def main():
    import cli
    dev = cli.connect(PORT, 1.0)
    if not dev:
        return 2
    results = []

    def check(name, ok, note=""):
        results.append((name, ok, note))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<40} {note}")

    def line(s, n=5):
        """Median of n round trips: one USB hiccup must not look like a broken clock."""
        times = []
        for _ in range(n):
            t0 = time.time()
            dev.cmd(s, timeout=10.0, allow_error=True)
            times.append(time.time() - t0)
        times.sort()
        return times[len(times) // 2]

    try:
        base = line("HERE .")
        m0 = line("0 MS")
        m100 = line("100 MS")
        m300 = line("300 MS")
        print(f"  round trip {base * 1000:.0f} ms | 0 MS {m0 * 1000:.0f} | "
              f"100 MS {m100 * 1000:.0f} | 300 MS {m300 * 1000:.0f}")
        d0, d100, d300 = (m0 - base) * 1000, (m100 - base) * 1000, (m300 - base) * 1000
        print(f"  minus baseline:  0 MS {d0:+.0f} ms | 100 MS {d100:+.0f} ms | 300 MS {d300:+.0f} ms")

        check("0 MS costs nothing", abs(d0) < 40, f"{d0:+.0f} ms")
        check("100 MS waits ~100 ms", 75 <= d100 <= 200, f"{d100:+.0f} ms")
        check("300 MS waits ~300 ms", 225 <= d300 <= 450, f"{d300:+.0f} ms")
        # The two-point slope is the clock itself, free of the round-trip constant and of per-line overhead.
        slope = (m300 - m100) * 1000 / 200.0
        check("the two points are consistent (a clock, not a constant)", 0.75 <= slope <= 1.25,
              f"200 ms of sleep took {(m300 - m100) * 1000:.0f} ms -> x{slope:.2f}")
        got = dev.num("2 3 + .", timeout=5.0)
        check("the REPL still answers after a wait", got == 5, f"2 3 + . = {got}")
    finally:
        dev.close()
    bad = sum(1 for _, ok, _ in results if not ok)
    print(f"\n  {len(results) - bad}/{len(results)} checks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
