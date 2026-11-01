#!/usr/bin/env python3
"""step4b.py — STEP 4b items. `dry` costs no chip run; the rest are one session each.

Item 1's sentinel needed care, and the original reasoning was WRONG: this machine DOES keep the data stack across lines
(`1 2 3` then `.` answers 3, then 2, then 1 - measured). The earlier "no persistence" conclusion came from
`40 3 BLKXFER` followed by `.`, where BLKXFER's ( addr st ) pair meant the status had already been consumed and only the
buffer address was left. What the sentinel actually measures is stack HEALTH per cycle.
"""
import sys, re, pathlib, subprocess, statistics, time
sys.path.insert(0, "tools")
from devio import Dev
sys.path.insert(0, "tests")
from step4 import phase_src, host_expect, build_and_adopt, IMG_AREA, DATA, PAT

CTRL = 1536
wd = pathlib.Path(".auto/tmp")


def dry():
    """Host-only dry run: 15 distinct oracles, and 14 source-load cycles with a stack-health check after each."""
    exp = {p: host_expect(p, wd) for p in range(1, 16)}
    distinct = len(set(map(tuple, exp.values())))
    print(f"  oracles: {distinct}/15 distinct  (p1 {exp[1]}, p14 {exp[14]}, p15 {exp[15]})")
    blocks = phase_src(1)
    bf = wd / "dry.blocks"
    bf.write_text("".join(f"{8+k} {b.encode().hex()}\n" for k, b in enumerate(blocks))
                  + f"2 {(' '*128).encode().hex()}\n" + f"{DATA(1)} {PAT(1).encode().hex()}\n")
    lines = ["SEAL", "2 OVL"]
    for cyc in range(1, 15):
        lines += [f"{8+k} LOAD" for k in range(len(blocks))]
        # GUARDRAIL: the probe must END the line. `32 EMIT` leaves it appended to the phase output, so it is not a
        # standalone "3" and the parser sees zero probes. `10 EMIT` emits a newline.
        lines += ["RUNPH1", "10 EMIT 1 2 + . 10 EMIT"]   # newline, probe, newline => a standalone "3"
        lines += ["2 OVL", "SEAL"]                       # the same rewind/seal the device loop performs
    dr = wd / "dry.fs"
    dr.write_text("\n".join(lines) + "\n")
    out = subprocess.run(["artifacts/host_blk", "-B", str(bf), "-k", "src/p39_prelude.fs",
                          "src/p39b_overlay.fs", str(dr)], capture_output=True).stdout.decode("latin-1")
    # GUARDRAIL: the probe is its own LINE ("3 "), because `.` emits a trailing space and the host does not echo. An
    # earlier filter matched any line CONTAINING "3" and collected the phase outputs (concat of six numbers) as probe
    # failures - the harness was blamed for the parser again.
    probes = [ln.strip() for ln in out.splitlines() if ln.strip() == "3"]
    healthy = len(probes)
    print(f"  host 14 cycles + health probe each: {'PASS' if distinct == 15 and healthy == 14 else 'FAIL'}"
          f"  ({healthy}/14 probes answered 3, {distinct}/15 distinct oracles)")
    return 0 if distinct == 15 and healthy == 14 else 1


def phase14_alone():
    """Item 1b: phase 14 on a FRESHLY reset board, on its own."""
    exp = host_expect(14, wd)
    with Dev() as d:                                   # Dev() hard-resets on open
        d.cmd("0 BLOCK CONSTANT W")
        ok, got, note = build_and_adopt(d, 14, IMG_AREA, phase_src(14))
        print(f"  phase 14 alone (fresh reset): adopted={ok} cells={got} expected {exp} {note}")
        print(f"  item1b: {'PASS' if ok and got == exp else 'FAIL'}")
    return 0


def sentinel():
    """Item 1a: 14 cycles with a stack-health probe after each; report the first cycle that is not healthy."""
    with Dev() as d:
        d.cmd("0 BLOCK CONSTANT W")
        first_bad = None
        for cyc in range(1, 15):
            ok, got, note = build_and_adopt(d, cyc, IMG_AREA + (cyc - 1) * 5, phase_src(cyc))
            probe = d.cmd("10 EMIT 1 2 + . 10 EMIT", timeout=10.0)
            healthy = "3" in [x for x in Dev.nums(probe)[-1:]] or Dev.nums(probe)[-1:] == [3]
            if not healthy and first_bad is None:
                first_bad = (cyc, probe.strip().replace("\r", " "))
            print(f"  cycle {cyc:2d}: adopted={ok} probe={'ok' if healthy else probe.strip()[:40]!r}")
            if not healthy:
                break
        print(f"  item1a first unhealthy cycle: {first_bad if first_bad else 'none in 14'}")
    return 0


def all_phases_and_timing():
    """Items 3 and 4: 15 phases from images with per-phase signatures, then 200 timed loads."""
    exp = {p: host_expect(p, wd) for p in range(1, 16)}
    bad = []
    with Dev() as d:
        d.cmd("0 BLOCK CONSTANT W")
        for p in range(1, 16):
            desc = IMG_AREA + (p - 1) * 5
            ok, got, note = build_and_adopt(d, p, desc, phase_src(p))
            if not (ok and got == exp[p]):
                bad.append((p, ok, got, exp[p], note))
            print(f"  phase {p:2d}: {'PASS' if ok and got == exp[p] else 'FAIL'} {got}")
        times = []
        for _ in range(200):
            d.cmd("2 OVL")
            t0 = time.monotonic()
            d.cmd(f"{IMG_AREA} 3 BLKXFER . DROP", timeout=25.0)
            times.append((time.monotonic() - t0) * 1000)
    times.sort()
    print(f"  item3: {15 - len(bad)}/15 phases executed from images" + (f" FAILED {bad[:2]}" if bad else ""))
    print(f"  item4 apply round trip x200: min {times[0]:.1f}  median {statistics.median(times):.1f}  "
          f"p99 {times[197]:.1f}  worst {times[-1]:.1f} ms")
    print(f"  item4 proposed bound = 845 - {times[-1]:.0f} - 200 = {845 - times[-1] - 200:.0f} ms "
          f"(400 ms currently {'generous' if 845 - times[-1] - 200 > 400 else 'TIGHT'}); bound NOT changed")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit({"dry": dry, "p14": phase14_alone, "sentinel": sentinel, "all": all_phases_and_timing}[sys.argv[1]]())
