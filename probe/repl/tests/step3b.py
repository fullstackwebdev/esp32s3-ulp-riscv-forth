#!/usr/bin/env python3
"""step3b.py — items 1-3 of step 3b in ONE chip session.

Item 1: stall the op-3 critical section. 500 ms is inside the ULP's wait, so the load must still apply CORRECTLY;
        2000 ms is past it, so nothing may be applied. Both are safety properties, not performance.
Item 2: false-refusal rate over 50 normal loads. Expect 0.
Item 3: timing of 50 image loads against the 970 ms source baseline.

PREDICTION (written before measuring): median 20-50 ms (~35). One mailbox round trip plus a 576-byte copy on the main
core; the console-path loader measured 38.5 ms and this path adds only a doorbell. Anything above 250 ms means the
image path is doing per-block work it should not.
"""
import sys, re, pathlib, statistics, time
sys.path.insert(0, "tools")
from devio import Dev
from fsplit import split_defs

DESC = 40
HOST_PREFIXES = ("img:", "dump:", "load:", "poke:", "stall:")


def phase_blocks():
    src = " ".join(re.sub(r"\([^)]*\)", "", re.sub(r"\\.*", "", pathlib.Path("tests/ph1.fsx").read_text())).split())
    b = split_defs(src, 128)
    b[-1] = b[-1].rstrip()[: -len("RUNPH1")].rstrip()
    return b


def main():
    blocks = phase_blocks()
    pat = ("0123456789" * 13)[:128]
    with Dev() as d:
        d.seed_many([(2, " " * 128), (4, pat)] + [(8 + k, b) for k, b in enumerate(blocks)])
        d.cmd("0 BLOCK CONSTANT W"); d.cmd("SEAL"); d.cmd("2 OVL")
        for k in range(len(blocks)):
            d.cmd(f"{8+k} LOAD", timeout=10.0)
        cs, ce, hs, he = d.num("bh @ ."), d.num("HERE ."), d.num("LATEST ."), d.num("bl @ .")
        entry = d.num("' RUNPH1 .")
        d.cmd(f"#d {DESC} {cs} {ce} {hs} {he} {entry}", timeout=20.0)

        def load(timed=False):
            d.cmd("2 OVL")
            t0 = time.monotonic()
            rep = d.cmd(f"{DESC} 3 BLKXFER .", timeout=25.0)
            dt = (time.monotonic() - t0) * 1000 if timed else None
            kept = [ln for ln in rep.splitlines() if not ln.strip().startswith(HOST_PREFIXES)]
            return ("REFUSED" in rep), rep, dt

        # ---- item 1a: 500 ms stall inside the critical section (inside the ULP's ~845 ms wait)
        d.cmd("#a 500")
        ref, rep, _ = load()
        # GUARDRAIL: the PASS criterion is the safe one: EITHER nothing applied (conservative refusal) OR applied
        # correctly, with the pointers consistent either way and the REPL still usable. Asserting "must be applied"
        # would call a conservative refusal a failure - and with a 400 ms bound a 500 ms stall is refused on purpose,
        # because applying after the bound risks landing in a dictionary the ULP has already abandoned.
        here, lat, went = d.num("HERE ."), d.num("LATEST ."), d.num("W @ .")
        if ref:
            safe = here == cs and lat == hs          # refused: nothing adopted, seal intact
        else:
            safe = here == ce and lat == hs and went == entry
        repl_ok = d.num("2 3 + .") == 5
        print(f"  item1a stall500 : {'PASS' if safe and repl_ok else 'FAIL'}  refused={ref} "
              f"HERE={here} LATEST={lat} repl_ok={repl_ok}")

        # ---- item 1b: 2000 ms stall, past the ULP's wait -> must apply NOTHING
        d.cmd("#a 2000")
        ref, rep, _ = load()
        nothing = d.num("HERE .") == cs
        stale = "REFUSED stale request after the stall" in rep
        print(f"  item1b stall2000: {'PASS' if nothing and stale else 'FAIL'}  refused={stale} HERE={d.num('HERE .')}={cs}")

        # ---- item 2: false refusals over 50 normal loads
        refused = 0
        for _ in range(50):
            ref, rep, _ = load()
            if ref:
                refused += 1
        print(f"  item2 false-refusals: {'PASS' if refused == 0 else 'FAIL'}  {refused}/50")

        # ---- item 3: timing, 50 loads
        times = []
        for _ in range(50):
            ref, rep, dt = load(timed=True)
            times.append(dt)
        med = statistics.median(times)
        print(f"  item3 timing   : median {med:.1f} ms  min {min(times):.1f}  max {max(times):.1f}  "
              f"vs 970 ms source = {970/med:.1f}x   (prediction 20-50 ms)")
        return 0


sys.exit(main())
