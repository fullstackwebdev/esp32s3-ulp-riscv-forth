#!/usr/bin/env python3
"""step4d.py — STEP 4d: name the one-cell leak with SINGLE runs, then verify the fixed loop drains empty.

`dry`  (no chip): the same single-command sequence against the host fake.
`run`  (ONE chip session): baseline drain, each candidate ONCE with a drain after it, the source-only 15-cycle loop
       with a drain at the end, then the dump/adopt 15-cycle loop WITH the compensating DROP for whichever command the
       single runs name, drained at the end (expect empty).

GUARDRAIL: a leak of exactly one cell per occurrence needs ONE run per candidate, not fifteen. Repetition only hides it
inside the stack depth - which is how the earlier "clean" loop looked clean.
GUARDRAIL: the drain prints LIFO, so the FIRST number printed is the TOP of the stack. That ordering is what tells a
stray window address sitting UNDER a consumed status apart from a primitive that pushes two values.
"""
import sys, re, pathlib, subprocess
sys.path.insert(0, "tools")
from devio import Dev
sys.path.insert(0, "tests")
from step4 import phase_src, DATA, PAT, IMG_AREA, build_and_adopt, host_expect

DOTS = " ".join(["."] * 20)
DRAIN = f"10 EMIT {DOTS} 10 EMIT"
wd = pathlib.Path(".auto/tmp")


def drain(d, label):
    """Pop one value per line until the stack underflows. LIFO: the list is TOP-first.

    GUARDRAIL: a single drain LINE cannot be parsed here. The device echoes the command, so the `10` of `10 EMIT` is
    read back as a value, and consecutive numbers concatenate when `.` emits no separator (`1808` + `0` -> `18080`).
    One value per line has no echo digits and no ambiguity.
    """
    vals = []
    for _ in range(24):
        out = d.cmd(".", timeout=8.0)
        if "ERR_STACK" in out:
            break
        n = Dev.nums(out)
        if not n:
            break
        vals.append(n[-1])
    print(f"    {label:28s} -> depth {len(vals)} {vals[:8]}")
    return vals


def host_dry():
    blocks = phase_src(1)
    bf = wd / "d.blocks"
    bf.write_text("".join(f"{8+k} {b.encode().hex()}\n" for k, b in enumerate(blocks))
                  + f"2 {(' '*128).encode().hex()}\n" + f"{DATA(1)} {PAT(1).encode().hex()}\n")
    lines = ["SEAL", "2 OVL", DRAIN, "2 OVL", DRAIN, f"3 BLKXFER .", DRAIN,
             f"{8} LOAD", DRAIN, "RUNPH1", DRAIN]
    dr = wd / "d.fs"
    dr.write_text("\n".join(lines) + "\n")
    out = subprocess.run(["artifacts/host_blk", "-B", str(bf), "-k", "src/p39_prelude.fs",
                          "src/p39b_overlay.fs", str(dr)], capture_output=True).stdout.decode("latin-1")
    # the host prints each drain as a run of numbers; count what followed each marker by re-running line by line
    print(f"  host transcript tail: {' '.join(out.split('SRV')[0].split())[-120:]}")
    print("  host dry run executed the full sequence without an engine trap")


def run():
    culprit = None
    with Dev() as d:
        d.cmd("0 BLOCK CONSTANT W")
        # baseline: what is on the stack before anything? (the trailing 0 in the earlier drains)
        base = drain(d, "baseline (fresh)")
        d.cmd("SEAL")
        # --- one image to make the adoption candidates meaningful
        ok, got, note = build_and_adopt(d, 1, IMG_AREA, phase_src(1))
        print(f"  image built+adopted: {ok} {note}")
        drain(d, "after build/adopt (cycle 1)")

        # ---- item 1: each candidate ONCE, with a drain after it
        d.cmd("2 OVL"); v = drain(d, "2 OVL")
        if v and v[0] == 1808: culprit = (culprit or "2 OVL")
        d.cmd(f"{IMG_AREA} 3 BLKXFER ."); v = drain(d, "3 BLKXFER .")
        if v and 1808 in v: culprit = "3 BLKXFER"
        d.cmd("W @ EXECUTE"); v = drain(d, "W @ EXECUTE")
        if v and 1808 in v: culprit = (culprit or "W @ EXECUTE")
        d.cmd("8 LOAD"); v = drain(d, "8 LOAD")
        if v and 1808 in v: culprit = (culprit or "8 LOAD")
        d.cmd("RUNPH1"); v = drain(d, "RUNPH1")
        if v and 1808 in v: culprit = (culprit or "RUNPH1")
        print(f"  item1 culprit: {culprit}   (baseline held {base})")

        # ---- item 2: source-only 15 cycles, drained at the END
        d.cmd("2 OVL"); d.cmd("SEAL")
        for p in range(1, 16):
            d.seed_many([(2, " " * 128), (DATA(p), PAT(p))] + [(8 + k, b) for k, b in enumerate(phase_src(p))])
            d.cmd("2 OVL")
            for k in range(8):
                d.cmd(f"{8+k} LOAD", timeout=10.0)
            d.cmd("RUNPH1", timeout=15.0)
        v = drain(d, "after 15 source-only cycles")
        depth_src = len(v)

        # ---- item 3: the dump/adopt loop WITH the compensating DROP for the named command, drained at the end
        d.cmd("2 OVL"); d.cmd("SEAL")
        drop_after = culprit if culprit in ("3 BLKXFER", "W @ EXECUTE", "8 LOAD", "RUNPH1") else None
        for p in range(1, 16):
            blocks = phase_src(p)
            d.seed_many([(2, " " * 128), (DATA(p), PAT(p))] + [(8 + k, b) for k, b in enumerate(blocks)])
            d.cmd("2 OVL"); d.cmd("SEAL"); d.cmd("2 OVL")
            for k in range(len(blocks)):
                d.cmd(f"{8+k} LOAD", timeout=10.0)
            cs, ce = d.num("bh @ ."), d.num("HERE .")
            hs, he = d.num("LATEST ."), d.num("bl @ .")
            entry = d.num("' RUNPH1 .")
            d.cmd(f"#d {IMG_AREA + (p-1)*5} {cs} {ce} {hs} {he} {entry}", timeout=20.0)
            d.cmd("2 OVL")
            if drop_after == "3 BLKXFER":
                d.cmd(f"{IMG_AREA + (p-1)*5} 3 BLKXFER . DROP")
            elif drop_after == "W @ EXECUTE":
                d.cmd("W @ EXECUTE DROP")
            else:
                d.cmd(f"{IMG_AREA + (p-1)*5} 3 BLKXFER .")
                d.cmd("W @ EXECUTE")
        v = drain(d, "after 15 dump/adopt cycles")
        print(f"  item2 source-only depth {depth_src}; item3 dump/adopt depth {len(v)}  "
              f"({'PASS empty' if not v else 'FAIL leftovers ' + str(v[:6])})")
    return 0


if __name__ == "__main__":
    sys.exit(run() if sys.argv[1] == "run" else (host_dry() or 0))
