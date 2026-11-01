#!/usr/bin/env python3
"""device_timing.py — the numbers the paging model is missing: block round trip, phase load, switch cost.

Uses tools/devio.py (prompt-driven, ~20 ms/command instead of 370 ms), so 50 load/drop cycles are affordable.

What each row means:
  BLOCK fetch      one block request answered by the main core: the floor for any data access.
  phase load       `SEAL; 2 OVL; N LOAD x blocks`: parse + compile + collision check for a whole phase.
  rel over source  same phase reloaded over its own previous overlay area (the steady-state switch cost).
"""
import sys, time, statistics
sys.path.insert(0, "tools")
from devio import Dev
from fsplit import split_defs
import pathlib, re

def main():
    phases = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    src = re.sub(r"\\.*", "", pathlib.Path("tests/ph1.fsx").read_text())
    src = " ".join(re.sub(r"\([^)]*\)", "", src).split())
    blocks = split_defs(src, 128)
    print(f"phase = {len(blocks)} blocks, {sum(len(b) for b in blocks)} B of source")

    with Dev() as d:
        for blk, text in ((8 + k, b) for k, b in enumerate(blocks)):
            if not d.seed(blk, text):
                print(f"FAIL seed of block {blk}"); return 1
        # GUARDRAIL: the rewind target is blanked through the SEEDER, not by typing a blanker word: interactive lines
        # are limited to CMD_SIZE-1 = 63 bytes, and the one-liner blanker is longer (it used to be truncated silently).
        if not d.seed(2, " " * 128):
            print("FAIL seed of block 2"); return 1
        d.cmd("SEAL")

        rt = []
        for _ in range(20):
            t0 = time.monotonic(); d.cmd("8 BLOCK"); rt.append(time.monotonic() - t0)
        print("  " + d.stats("BLOCK fetch", rt))

        loads, cycles = [], []
        for cyc in range(50):
            d.cmd("2 OVL")                      # clean overlay area
            t0 = time.monotonic()
            for k in range(len(blocks)):
                d.cmd(f"{8 + k} LOAD", timeout=10.0)
            loads.append(time.monotonic() - t0)
            cycles.append(loads[-1])
        med = statistics.median(loads)
        print("  " + d.stats("phase load (all blocks)", loads))
        print(f"  per block: {med/len(blocks)*1000:.1f} ms   per char of source: {med/sum(len(b) for b in blocks)*1e6:.0f} us")
        # correctness of the last load: the phase's first word must resolve
        print("  after 50 cycles: ' DATABLK ->", d.nums(d.cmd("' DATABLK ."))[-1])
    return 0

sys.exit(main())
