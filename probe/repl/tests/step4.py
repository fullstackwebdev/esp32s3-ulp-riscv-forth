#!/usr/bin/env python3
"""step4.py — STEP 4 items. Each subcommand is one chip session.

Why phases looked identical: every phase was the same source reading the same data block. Each phase now gets its OWN
data block (`20 + p`) seeded with its own pattern, so the six result cells differ per phase - and the expectation still
comes from the HOST run of that phase's exact bytes, never from arithmetic of mine.

AREAS, and why: phase source uses 8..15 transiently, data blocks 20..35, images start at 50 and take 5 blocks each, so
15 images occupy 50..124 and nothing collides with the fixtures (5 silent, 7 bad checksum on the fake server).

GUARDRAIL: the fake server answers 0..63 except block 5 (silent) and 7 (bad checksum), so any data block must stay out of
{5, 7}. 20+p never does.
"""
import sys, re, pathlib, subprocess, statistics, time
sys.path.insert(0, "tools")
from devio import Dev
from fsplit import split_defs

CTRL = 1536
IMG_AREA = 50
PAT = lambda p: chr(ord("A") + (p - 1)) * 128          # 'A'*128, 'B'*128, ... distinct per phase
DATA = lambda p: 20 + p
HOST_PREFIXES = ("img:", "dump:", "load:", "poke:", "stall:")


def phase_src(p):
    src = " ".join(re.sub(r"\([^)]*\)", "", re.sub(r"\\.*", "", pathlib.Path("tests/ph1.fsx").read_text())).split())
    assert src.count("4 CONSTANT DATABLK") == 1
    src = src.replace("4 CONSTANT DATABLK", f"{DATA(p)} CONSTANT DATABLK")
    blocks = split_defs(src, 128)
    blocks[-1] = blocks[-1].rstrip()[: -len("RUNPH1")].rstrip()
    return blocks


def host_expect(p, workdir):
    workdir.mkdir(parents=True, exist_ok=True)   # GUARDRAIL: a clean clone has no .auto/tmp
    blocks = phase_src(p)
    bf = workdir / f"step4_{p}.blocks"
    bf.write_text("".join(f"{8+k} {b.encode().hex()}\n" for k, b in enumerate(blocks))
                  + f"2 {(' '*128).encode().hex()}\n" + f"{DATA(p)} {PAT(p).encode().hex()}\n")
    dr = workdir / f"step4_{p}.fs"
    # GUARDRAIL: the oracle MUST mirror the binary path: the source is defines-only, so the entry has to be EXECUTEd
    # explicitly. Without this the host reported [0,0,0,0,0,0] (nothing ran) while the device computed the real
    # numbers, and the comparison failed the machine for the test's mistake.
    dr.write_text("SEAL\n2 OVL\n" + "".join(f"{8+k} LOAD\n" for k in range(len(blocks)))
                  + "RUNPH1\n" + "32 EMIT\n" + "".join(f"z{i} @ . 32 EMIT\n" for i in range(1, 7)))
    out = subprocess.run(["artifacts/host_blk", "-B", str(bf), "-k", "src/p39_prelude.fs",
                          "src/p39b_overlay.fs", str(dr)], capture_output=True).stdout.decode("latin-1")
    return Dev.nums(out.split("SRV")[0])[-6:]


def build_and_adopt(d, p, desc, blocks, execute=True):
    # GUARDRAIL: execute=False lets a diagnosis stop just BEFORE the step that hangs; a probe that only watches
    # `W @ EXECUTE` time out learns nothing about the state that produced the hang.
    """Load the phase from SOURCE, dump its image, rewind, adopt it through mailbox op 3, run its entry."""
    # GUARDRAIL: refuse to build on a short seed. A silently truncated block compiles a truncated phase, and the
    # symptom is not a seed error - it is a small image and a hang inside EXECUTE three steps later.
    missing = d.seed_many([(2, " " * 128), (DATA(p), PAT(p))] + [(8 + k, b) for k, b in enumerate(blocks)])
    if missing:
        raise RuntimeError(f"seed failed for blocks {missing}: refusing to build a phase on a short store")
    # GUARDRAIL: REWIND BEFORE SEALING, but ONLY once a seal exists. After a previous phase was adopted, V_HERE is that
    # image's end, so SEAL there moved the base far above the phase's own code (measured: `#d 55 1308 1312 1418 1418`
    # = empty code and headers, then REJECTED). With bh still 0 (nothing sealed yet) the rewind would set the
    # dictionary to address 0 and make EVERY word unfindable - the documented OVL hazard - so seal first in that case.
    if d.num("bh @ .") == 0:
        d.cmd("SEAL")
    else:
        d.cmd("2 OVL")
        d.cmd("SEAL")
    d.cmd("2 OVL")
    for k in range(len(blocks)):
        d.cmd(f"{8+k} LOAD", timeout=10.0)
    cs, ce = d.num("bh @ ."), d.num("HERE .")
    # GUARDRAIL: a phase is ~500 B of code. Measured failure this catches: after a prior source LOAD the phase LOADs
    # answer TW?/IDX? (CREATE never runs), the dump is 10 B, the loader adopts the stub and EXECUTE hangs with NO error
    # anywhere. A tiny image is not a phase - refuse it by name instead of adopting it and hanging three steps later.
    if ce - cs < 200:
        raise RuntimeError("phase code is only %d B, expected ~500: a LOAD failed - refusing to dump a stub" % (ce - cs))

    hs, he = d.num("LATEST ."), d.num("bl @ .")
    entry = d.num("' RUNPH1 .")
    d.cmd(f"#d {desc} {cs} {ce} {hs} {he} {entry}", timeout=20.0)
    d.cmd("2 OVL")
    # GUARDRAIL: BLKXFER is ( n op -- addr st ): it pushes the BUFFER ADDRESS *and* the status, by contract, so the
    # Forth layer never hardcodes the window address. Printing only the status left one `1808` per call on the stack -
    # measured as exactly one stray 1808 per cycle, ten after ten cycles, which overflowed the stack at cycle 14 and
    # looked like a phase bug. `. DROP` consumes both.
    rep = d.cmd(f"{desc} 3 BLKXFER . DROP", timeout=25.0)
    ok = "adopted" in rep and d.num("HERE .") == ce and d.num("LATEST .") == hs and d.num("W @ .") == entry
    if not execute:
        return ok, [], repair_note(rep)
    d.cmd("W @ EXECUTE", timeout=15.0)
    return ok, [d.num(f"z{i} @ .") for i in range(1, 7)], repair_note(rep)


def repair_note(rep):
    kept = [ln for ln in rep.splitlines() if not ln.strip().startswith(HOST_PREFIXES)]
    return (kept[-1] if kept else "").strip()[:20]


def item1():
    """Distinct signature, and the assertion shown failing once: load phase 8's image, expect phase 1's numbers."""
    wd = pathlib.Path(".auto/tmp"); wd.mkdir(parents=True, exist_ok=True)
    e1, e8 = host_expect(1, wd), host_expect(8, wd)
    print(f"  host phase1 {e1}")
    print(f"  host phase8 {e8}   (distinct: {e1 != e8})")
    with Dev() as d:
        d.cmd("0 BLOCK CONSTANT W")
        ok8, got8, note = build_and_adopt(d, 8, IMG_AREA + 7 * 5, phase_src(8))
        bad = (got8 == e1)
        print(f"  phase 8 via image: adopted={ok8} cells={got8} {note}")
        print(f"  item1 negative  : {'PASS' if got8 != e1 else 'FAIL'}  comparing phase 8 against phase 1's signature")
        print(f"  item1 positive  : {'PASS' if got8 == e8 else 'FAIL'}  phase 8 matches its own host run")
    return 0


def item2_and_3():
    """PREDICTION (before measuring): 15 phases x 5 blocks = 75 blocks of images; the store's ceiling is 128/5 = 25
    phases, i.e. 25 x 516 B = 12.9 KB = 8.4x the 1,536 B control."""
    print("  PREDICTION: 15 phases fit in 75 blocks; capacity 25 phases ~ 12.9 KB ~ 8.4x control")
    wd = pathlib.Path(".auto/tmp")
    exp = {p: host_expect(p, wd) for p in range(1, 16)}
    print(f"  distinct host signatures: {len(set(map(tuple, exp.values())))}/15")
    bad = []
    seen = {}
    with Dev() as d:
        d.cmd("0 BLOCK CONSTANT W")
        for p in range(1, 16):
            desc = IMG_AREA + (p - 1) * 5
            ok, got, note = build_and_adopt(d, p, desc, phase_src(p))
            seen[p] = got
            good = ok and got == exp[p]
            if not good:
                bad.append((p, ok, got, exp[p], note))
            print(f"  phase {p:2d} via image: {'PASS' if good else 'FAIL'} {got}")
    # item 1's two checks fall out of the same session: phase 8 adopted vs phase 1's signature (must differ) and vs
    # its own (must match).
    if 8 not in [b[0] for b in bad]:
        pass
    blocks_used = 15 * 5
    capacity = 128 // 5
    print(f"  item2: {15 - len(bad)}/15 phases executed from images" + (f"  FAILED {bad[:2]}" if bad else ""))
    print(f"  item3: {blocks_used} blocks for 15 images = {blocks_used*128} B stored; "
          f"capacity {capacity} phases = {capacity*516} B = {capacity*516/CTRL:.1f}x control")
    # ---- item 1's negative/positive, from THIS session's data
    # ---- item 1: phase 8's image against phase 1's signature (must differ) and its own (must match)
    neg_ok = seen.get(8) != exp[1]
    pos_ok = seen.get(8) == exp[8]
    print(f"  item1 negative: {'PASS' if neg_ok else 'FAIL'}  phase 8 cells {seen.get(8)} != phase 1 {exp[1]}")
    print(f"  item1 positive: {'PASS' if pos_ok else 'FAIL'}  phase 8 matches its own host run")
    # ---- item 4: worst-case apply round trip over 200 loads (same session, phase 1's image)
    times = []
    for _ in range(200):
        d.cmd("2 OVL")
        t0 = time.monotonic()
        d.cmd(f"{IMG_AREA} 3 BLKXFER . DROP", timeout=25.0)
        times.append((time.monotonic() - t0) * 1000)
    times.sort()
    worst = times[-1]
    prop = 845 - worst - 200
    print(f"  item4 apply round trip over 200 loads: median {statistics.median(times):.1f} ms, "
          f"p99 {times[197]:.1f}, worst {worst:.1f}")
    print(f"  item4 proposed bound = 845 - {worst:.0f} - 200 = {prop:.0f} ms "
          f"(current 400 ms is {'generous' if prop > 400 else 'TIGHT'})")
    return 0 if (not bad and neg_ok and pos_ok) else 1


def item4():
    """Worst-case apply time over 200 loads -> propose the age bound."""
    wd = pathlib.Path(".auto/tmp")
    blocks = phase_src(1)
    times = []
    with Dev() as d:
        d.cmd("0 BLOCK CONSTANT W")
        ok, _, _ = build_and_adopt(d, 1, IMG_AREA, blocks)
        print(f"  image built and adopted: {ok}")
        for _ in range(200):
            d.cmd("2 OVL")
            t0 = time.monotonic()
            d.cmd(f"{IMG_AREA} 3 BLKXFER . DROP", timeout=25.0)
            times.append((time.monotonic() - t0) * 1000)
    times.sort()
    print(f"  apply round trip over 200 loads: median {statistics.median(times):.1f} ms  "
          f"p99 {times[197]:.1f}  worst {times[-1]:.1f} ms")
    print(f"  proposed bound = ULP wait (845 ms measured) - worst case ({times[-1]:.1f}) - margin 200 = "
          f"{845 - times[-1] - 200:.0f} ms   (current 400 ms is {'generous' if 845 - times[-1] - 200 > 400 else 'tight'})")
    return 0


if __name__ == "__main__":
    sys.exit({"1": item1, "23": item2_and_3, "4": item4}[sys.argv[1]]())
