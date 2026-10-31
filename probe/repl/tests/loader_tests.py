#!/usr/bin/env python3
"""loader_tests.py — STEP 3: the binary loader's six tests, every refusal shown firing.

Builds an image with `#d`, adopts it with `#l`, and then breaks it four different ways. Each refusal prints by name; a
refusal that has never fired is not evidence.

GUARDRAIL: every case runs in ONE chip session. Rebuilding an image per case would cost a reset + 8 loads each, and the
chip-run budget for a probe is three.
GUARDRAIL: the expected outputs come from the SOURCE-loaded phase in the same session, not from a constant - the point is
that the binary path reproduces the source path, not that it reproduces my arithmetic.
"""
import sys, re, pathlib
sys.path.insert(0, "tools")
from devio import Dev
from fsplit import split_defs

DESC = 40
EXPECT6 = None


def phase():
    src = " ".join(re.sub(r"\([^)]*\)", "", re.sub(r"\\.*", "", pathlib.Path("tests/ph1.fsx").read_text())).split())
    return split_defs(src, 128)


def cells(d):
    return [d.num(f"z{i} @ .") for i in range(1, 7)]


def main():
    blocks = phase()
    pat = ("0123456789" * 13)[:128]
    out = []
    with Dev() as d:
        miss = d.seed_many([(2, " " * 128), (4, pat)] + [(8 + k, b) for k, b in enumerate(blocks)])
        if miss:
            print("seed failed", miss); return 1
        d.cmd("SEAL"); d.cmd("2 OVL")
        for k in range(len(blocks)):
            d.cmd(f"{8+k} LOAD", timeout=10.0)
        expect = cells(d)
        cs, ce = d.num("bh @ ."), d.num("HERE .")
        hs, he = d.num("LATEST ."), d.num("bl @ .")
        dump = d.cmd(f"#d {DESC} {cs} {ce} {hs} {he}", timeout=20.0).strip().splitlines()[-1]
        print(f"  dump: {dump}")
        nblocks = int(re.search(r"-> (\d+) blocks", dump).group(1))

        # --- T1 adopt and EXECUTE
        d.cmd("2 OVL")
        load = d.cmd(f"#l {DESC}", timeout=20.0).strip().splitlines()[-1]
        got = cells(d)
        ok1 = ("adopted" in load) and got == expect
        print(f"  T1 adopt+execute      : {'PASS' if ok1 else 'FAIL'}  {load}")
        print(f"     cells {got} vs source {expect}")

        # --- T2 block count
        ok2 = nblocks < len(blocks)
        print(f"  T2 block count        : {'PASS' if ok2 else 'FAIL'}  image {nblocks} < source {len(blocks)}")

        # --- T3 fifty load/drop cycles, pointers return to the sealed values every time
        ok3 = True
        for cyc in range(50):
            d.cmd("2 OVL")
            if d.num("HERE bh @ - .") != 0 or d.num("LATEST bl @ - .") != 0:
                ok3 = False; break
            d.cmd(f"#l {DESC}", timeout=20.0)
        print(f"  T3 50 load/drop cycles: {'PASS' if ok3 else 'FAIL'}")

        # --- T4 image payload corrupted -> named refusal, nothing executes
        d.cmd("2 OVL")
        d.cmd(f"#p {DESC} 20 255")
        r4 = d.cmd(f"#l {DESC}", timeout=20.0).strip().splitlines()[-1]
        ok4 = "REFUSED" in r4 and "corrupt" in r4
        print(f"  T4 corrupt payload    : {'PASS' if ok4 else 'FAIL'}  {r4}")

        # --- T5 descriptor's resident sum does not match this dictionary
        d.cmd(f"#p {DESC} 13 0"); d.cmd(f"#p {DESC} 14 0")
        r5 = d.cmd(f"#l {DESC}", timeout=20.0).strip().splitlines()[-1]
        ok5 = "REFUSED" in r5 and "resident" in r5
        print(f"  T5 resident changed   : {'PASS' if ok5 else 'FAIL'}  {r5}")

        # --- T6 an image header whose hash matches a resident one
        # GUARDRAIL: forging a header byte also changes the payload sum, so a naive test measures refusal 3 (corrupt)
        # and never reaches the collision check - measured as T6 answering "image corrupt". A hostile/different builder
        # would fix the sum too, so the test must do the same: recompute psum over the 3 swapped bytes and rewrite it.
        d.cmd("2 OVL")
        for k in range(len(blocks)):
            d.cmd(f"{8+k} LOAD", timeout=10.0)
        dump2 = d.cmd(f"#d {DESC} {cs} {ce} {hs} {he}", timeout=20.0).strip().splitlines()[-1]
        psum = [d.num(f"{DESC} BLOCK {11+j} + C@ .") for j in range(2)]
        psum = psum[0] | (psum[1] << 8)
        # GUARDRAIL: the resident header AREA is [sealed LATEST, HDRTOP) - `he` is its lowest address, i.e. the newest
        # resident header sits AT `he`, not at he-3. Using he-3 pointed into the IMAGE's own headers, so the forgery
        # created no collision at all and the loader correctly adopted it (measured as T6 answering "adopted").
        res_hdr = he                                        # newest RESIDENT header
        img_hdr = 16 + (ce - cs)                            # first IMAGE header inside the payload
        delta = 0
        for j in range(3):
            # GUARDRAIL: the resident header lives in MEMORY at the address the descriptor reports, so read it as
            # `addr C@` - reading `N BLOCK` instead addresses a STORE block, and block 11 holds phase source text.
            # Measured: the forgery copied source text into an image header, no collision existed, and T6 "adopted".
            v = d.num(f"{res_hdr + j} C@ .")
            g, o = DESC + (img_hdr + j) // 128, (img_hdr + j) % 128
            old = d.num(f"{g} BLOCK {o} + C@ .")
            d.cmd(f"#p {g} {o} {v}")
            delta += v - old
        psum2 = (psum + delta) & 0xffff
        d.cmd(f"#p {DESC} 11 {psum2 & 0xff}"); d.cmd(f"#p {DESC} 12 {(psum2 >> 8) & 0xff}")
        d.cmd("2 OVL")
        r6 = d.cmd(f"#l {DESC}", timeout=20.0).strip().splitlines()[-1]
        ok6 = "REFUSED" in r6 and "collision" in r6
        print(f"  T6 header collision   : {'PASS' if ok6 else 'FAIL'}  {r6}")

    fails = [n for n, ok in (("T1", ok1), ("T2", ok2), ("T3", ok3), ("T4", ok4), ("T5", ok5), ("T6", ok6)) if not ok]
    print(f"  result: {6 - len(fails)}/6 pass" + (f", failed {fails}" if fails else ""))
    return 1 if fails else 0


sys.exit(main())
