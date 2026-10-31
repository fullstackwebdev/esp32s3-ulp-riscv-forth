#!/usr/bin/env python3
"""loader_tests.py — the binary image loader, exercised the only safe way: mailbox op 3.

Design (from review):
  * the ULP asks for the image and blocks inside blk_xfer, so the main core writes mem[] while the ULP is provably
    quiescent. `#l` (a console command that wrote mem[] while the REPL ran) is RETIRED and refuses.
  * the descriptor carries an ENTRY XT, because a binary load cannot run what a phase's top-level text ran. The entry
    rides back in the block window and the caller EXECUTEs it.
  * a phase must DEFINE things and nothing else at top level; the dump is taken before it runs, so captured data holds
    initial values rather than the leftovers of a run.

GUARDRAIL: proving "it executes" needs the cells cleared after adoption and the entry called - comparing cells right
after a load only proves the bytes came back, because the dump captured them after the source phase ran (that mistake
made an earlier version of T1 look green for the wrong reason).
"""
import sys, re, pathlib
sys.path.insert(0, "tools")
from devio import Dev
from fsplit import split_defs

DESC = 40


def phase_blocks_defines_only():
    """The phase source with the trailing top-level `RUNPH1` removed: phases define, callers execute."""
    src = " ".join(re.sub(r"\([^)]*\)", "", re.sub(r"\\.*", "", pathlib.Path("tests/ph1.fsx").read_text())).split())
    blocks = split_defs(src, 128)
    last = blocks[-1]
    assert last.rstrip().endswith("RUNPH1"), last[-40:]
    blocks[-1] = last.rstrip()[: -len("RUNPH1")].rstrip()
    return blocks


def main():
    blocks = phase_blocks_defines_only()
    pat = ("0123456789" * 13)[:128]
    with Dev() as d:
        miss = d.seed_many([(2, " " * 128), (4, pat)] + [(8 + k, b) for k, b in enumerate(blocks)])
        if miss:
            print("seed failed", miss); return 1
        d.cmd("0 BLOCK CONSTANT W")                 # window address, before any image disturbs the window
        d.cmd("SEAL"); d.cmd("2 OVL")
        for k in range(len(blocks)):
            d.cmd(f"{8+k} LOAD", timeout=10.0)
        cs, ce = d.num("bh @ ."), d.num("HERE .")
        hs, he = d.num("LATEST ."), d.num("bl @ .")
        entry = d.num("' RUNPH1 .")
        cells0 = [d.num(f"z{i} @ .") for i in range(1, 7)]          # must still be initial values
        dump = d.cmd(f"#d {DESC} {cs} {ce} {hs} {he} {entry}", timeout=20.0).strip().splitlines()[-1]
        print(f"  dump (before running): {dump}")
        print(f"  cells at dump time   : {cells0}   entry xt {entry}")

        def load():
            d.cmd("2 OVL")                                        # rewind, so V_HERE == sealed HERE
            return d.cmd(f"{DESC} 3 BLKXFER .", timeout=20.0).strip()

        # --- T1 adopt + EXECUTE the returned entry
        st = load()
        adopted = [d.num(f"z{i} @ .") for i in range(1, 7)]
        got_entry = d.num("W @ .")
        for i in range(1, 7):
            d.cmd(f"0 z{i} !")
        d.cmd("W @ EXECUTE", timeout=15.0)
        ran = [d.num(f"z{i} @ .") for i in range(1, 7)]
        ok1 = "0" in st.split()[-1:] and got_entry == entry and adopted == cells0 and ran == [6712, 353000, 0, 57, 128, 38]
        print(f"  T1 adopt+execute      : {'PASS' if ok1 else 'FAIL'}  status {st.split()[-1]}, entry {got_entry}, "
              f"after EXECUTE {ran}")

        # --- T2 block count
        nblocks = int(re.search(r"-> (\d+) blocks", dump).group(1))
        print(f"  T2 block count        : {'PASS' if nblocks < len(blocks) else 'FAIL'}  image {nblocks} < source {len(blocks)}")

        # --- T3 fifty load cycles: sealed pointers restored every time
        ok3 = True
        for _ in range(50):
            load()
            if d.num("HERE bh @ - .") != 0 or d.num("LATEST bl @ - .") != 0:
                ok3 = False; break
            if d.num("W @ .") != entry:
                ok3 = False; break
        print(f"  T3 50 load cycles     : {'PASS' if ok3 else 'FAIL'}")

        # --- T4 corrupt one image byte -> BK_CRC (-4)
        d.cmd(f"#p {DESC} 24 255")
        st4 = load()
        print(f"  T4 corrupt payload    : {'PASS' if st4.split()[-1] == '-4' else 'FAIL'}  status {st4.split()[-1]}")

        # --- T5 stale resident checksum -> BK_CRC (-4). Forge the descriptor's resident sum.
        d.cmd(f"#d {DESC} {cs} {ce} {hs} {he} {entry}", timeout=20.0)
        d.cmd(f"#p {DESC} 13 0"); d.cmd(f"#p {DESC} 14 0")
        st5 = load()
        print(f"  T5 resident changed   : {'PASS' if st5.split()[-1] == '-4' else 'FAIL'}  status {st5.split()[-1]}")

        # --- T6 header collision -> BK_BUFOVER (-6). Copy a resident header over an image header and fix the image sum.
        d.cmd(f"#d {DESC} {cs} {ce} {hs} {he} {entry}", timeout=20.0)
        psum = d.num(f"{DESC} BLOCK 11 + C@ .") | (d.num(f"{DESC} BLOCK 12 + C@ .") << 8)
        res_hdr = he                                             # newest resident header sits AT sealed LATEST
        img_hdr = 20 + (ce - cs)                                 # first image header in the payload
        delta = 0
        for j in range(3):
            v = d.num(f"{res_hdr + j} C@ .")
            g, o = DESC + (img_hdr + j) // 128, (img_hdr + j) % 128
            old = d.num(f"{g} BLOCK {o} + C@ .")
            d.cmd(f"#p {g} {o} {v}")
            delta += v - old
        psum2 = (psum + delta) & 0xFFFF
        d.cmd(f"#p {DESC} 11 {psum2 & 0xFF}"); d.cmd(f"#p {DESC} 12 {(psum2 >> 8) & 0xFF}")
        st6 = load()
        print(f"  T6 header collision   : {'PASS' if st6.split()[-1] == '-6' else 'FAIL'}  status {st6.split()[-1]}")

        # --- T7 wrong sealed pointers -> BK_RANGE (-5): build an image, then move the seal by defining a word
        d.cmd(f"#d {DESC} {cs} {ce} {hs} {he} {entry}", timeout=20.0)
        d.cmd(": MOVESEAL 1 ;")                                   # this moves HERE (and LATEST) past the seal
        st7 = load()                                              # the rewind undoes the overlay, so move the seal instead:
        # 2 OVL rewinds, so re-create the drift the way a different resident build would: lie in the descriptor
        d.cmd(f"#d {DESC} {cs} {ce} {hs} {he} {entry}", timeout=20.0)
        d.cmd(f"#p {DESC} 7 {(cs + 2) & 0xFF}"); d.cmd(f"#p {DESC} 8 {((cs + 2) >> 8) & 0xFF}")
        st7b = load()
        print(f"  T7 sealed pointers    : {'PASS' if st7b.split()[-1] == '-5' else 'FAIL'}  status {st7b.split()[-1]}")

        # --- T8 the BLK_SZ(256) vs blk_sz(128) regression: bytes past offset 128 must survive
        d.cmd(f"#d {DESC} {cs} {ce} {hs} {he} {entry}", timeout=20.0)
        bad = 0
        for off in (0, 127, 128, 300, 500):
            mem = d.num(f"bh @ {off} + C@ .")
            g = 20 + off
            img = d.num(f"{DESC + g // 128} BLOCK {g % 128} + C@ .")
            if mem != img:
                bad += 1
        print(f"  T8 payload past 128   : {'PASS' if bad == 0 else 'FAIL'}  {5 - bad}/5 offsets byte-exact")

        fails = [] if all([ok1, nblocks < len(blocks), ok3, st4.split()[-1] == "-4", st5.split()[-1] == "-4",
                           st6.split()[-1] == "-6", st7b.split()[-1] == "-5", bad == 0]) else ["see above"]
        print(f"  result: {'8/8 pass' if not fails else 'FAILED ' + str(fails)}")
        return 0 if not fails else 1


sys.exit(main())
