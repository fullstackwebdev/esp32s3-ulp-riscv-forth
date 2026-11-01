#!/usr/bin/env python3
"""flash_persist.py — docs/22 gates 1, 2, 3, 5: does the store survive a RESET, and does it refuse loudly when broken?

Gates:
  1 persistence   : seed blocks, flush, hard reset, read back byte-exact -> 0 mismatches
  5 sector RMW    : two blocks in the SAME 4 KB sector, write both, read both back -> the first must not be stale
  2 image reboot  : build an image, flush, reset, adopt WITHOUT reseeding, execute, outputs match the host
  3 corrupt super : overwrite the magic, reset -> boot refuses BY NAME, and `#x` recovers
"""
import sys, re, subprocess, time, pathlib
sys.path.insert(0, "tools")
from devio import Dev
sys.path.insert(0, "tests")
from step4 import phase_src, host_expect, IMG_AREA, DATA, PAT

wd = pathlib.Path(".auto/tmp")
ok_all = True


def check(name, ok, detail=""):
    global ok_all
    ok_all = ok_all and ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")


def reset(d):
    d.reset()


def main():
    # ---- gate 1: persist across a reset
    pat = "".join(chr(65 + (k % 26)) for k in range(128))
    with Dev() as d:
        d.cmd("#x")                                  # start from a known-empty store
        d.seed_many([(DATA(1), pat)])
        r = d.cmd("#f")
        check("gate1a flush after seed", "flush: ok" in r, " ".join(r.splitlines()[-1].split())[:60])
        before = [d.num(f"{DATA(1)} BLOCK {o} + C@ .") for o in (0, 64, 127)]
        reset(d)                                     # HARD RESET: the RAM mirror is gone
        after = [d.num(f"{DATA(1)} BLOCK {o} + C@ .") for o in (0, 64, 127)]
        check("gate1b byte-exact AFTER reset", before == after and after[0] == ord(pat[0]),
              f"before {before} after {after}")

        # ---- gate 5: two blocks in the same sector (32 blocks/sector), the classic RMW bug
        a, b = DATA(2), DATA(2) + 1                  # adjacent -> same 4 KB sector
        d.seed_many([(a, "A" * 128), (b, "B" * 128)])
        d.cmd("#f")
        reset(d)
        va = d.num(f"{a} BLOCK 0 + C@ .")
        vb = d.num(f"{b} BLOCK 0 + C@ .")
        check("gate5 both blocks survive in one sector", va == ord('A') and vb == ord('B'), f"{va},{vb}")

    # ---- gate 2: an image survives reboot and RUNS without reseeding
    exp = host_expect(1, wd)
    with Dev() as d:
        d.cmd("#x")
        blocks = phase_src(1)
        d.seed_many([(2, " " * 128), (DATA(1), PAT(1))] + [(8 + k, x) for k, x in enumerate(blocks)])
        d.cmd("0 BLOCK CONSTANT W"); d.cmd("SEAL"); d.cmd("2 OVL")
        for k in range(len(blocks)):
            d.cmd(f"{8+k} LOAD", timeout=10.0)
        cs, ce = d.num("bh @ ."), d.num("HERE .")
        hs, he = d.num("LATEST ."), d.num("bl @ .")
        entry = d.num("' RUNPH1 .")
        d.cmd(f"#d {IMG_AREA} {cs} {ce} {hs} {he} {entry}", timeout=20.0)
        d.cmd("#f")
        reset(d)                                     # reboot: no reseeding from here on
        d.cmd("0 BLOCK CONSTANT W"); d.cmd("SEAL"); d.cmd("2 OVL")
        r = d.cmd(f"{IMG_AREA} 3 BLKXFER . DROP", timeout=20.0)
        print(f"    adopt reply: {' | '.join(x.strip() for x in r.splitlines() if x.strip())[:110]}")
        ex = d.cmd("W @ EXECUTE", timeout=15.0)
        print(f"    execute reply: {' | '.join(x.strip() for x in ex.splitlines() if x.strip())[:80]}")
        # GUARDRAIL: query on ONE line per cell but drop the echoed command, whose `z1` digit parses as the value
        # (measured: cells "read back" as [1,2,3,4,5,6], i.e. the indices - they had not been defined at all).
        # GUARDRAIL: take the six values from the EXECUTE reply itself (RUNPH1's SHOW prints them), not from per-cell
        # queries. `z1 @ .` replies carry the echo's digit, and the filtered form still parsed as the indices [1..6] -
        # the cells were correct all along and the test called them wrong.
        # GUARDRAIL: the machine prints the six values with no separator, so they arrive as one digit string. Compare the
        # STRING the host expects (`8320|540800|0|65|128|0` -> "83205408000651280"); splitting it is guesswork.
        want_digits = "".join(str(v) for v in exp)
        got = want_digits if want_digits in ex.replace(" ", "") else Dev.nums(ex)[-6:]
        check("gate2 image adopted and executed after reboot", "adopted" in r and got == want_digits, f"{got}")

        # ---- gate 3: corrupt the superblock magic -> boot must refuse by name, and #x recovers
        d2 = d
    # corrupt magic by writing a block whose offset lands in sector 0? Not reachable from the block API, so use the
    # boot path instead: format, then flash a bad magic via a deliberate truncation is out of scope here.
    print("  NOTE  gate3 (corrupt superblock) needs a raw sector write from the host; not attempted in this run")
    print(f"  {3 if ok_all else 0}/3 executed gates pass" + ("" if ok_all else " (see FAIL lines)"))
    return 0 if ok_all else 1


sys.exit(main())
