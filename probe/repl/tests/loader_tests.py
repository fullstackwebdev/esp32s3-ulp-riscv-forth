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
HOST_PREFIXES = ("img:", "dump:", "load:", "poke:", "stall:")


def status_of(reply):
    """The status is the last number AFTER the host's own prefixed diagnostics are removed.

    GUARDRAIL: `img: adopted code 516 + hdr 60 from block 40, entry 1282` puts 1282 last in the transcript, so "the last
    number" is sometimes the entry xt (or the echoed op) instead of the status - measured as a correct adoption reported
    as status 3. Strip the host's lines first; what remains is the ULP's own output.
    """
    kept = [ln for ln in reply.splitlines() if not ln.strip().startswith(HOST_PREFIXES)]
    nums = Dev.nums("\n".join(kept))
    return str(nums[-1]) if nums else "no-status"


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
            # GUARDRAIL: the device echoes the command, so the reply's last TOKEN is the `ok` prompt while the last
            # NUMBER is the status. Parsing tokens read every refusal as "ok".
            d.cmd("2 OVL")                                        # rewind, so V_HERE == sealed HERE
            # GUARDRAIL: do NOT print the status on the same line as the request. The host's own "img: adopted ...
            # entry 1282" line lands in the same transcript, so "the last number" is sometimes 1282 or the echoed op
            # (3) instead of the status - measured as a correct adoption reported as status 3. Push it, then print it
            # alone: a lone `.` has no digits in its echo.
            reply = d.cmd(f"{DESC} 3 BLKXFER .", timeout=20.0)
            # GUARDRAIL: return BOTH. The status digits can arrive after the `ok` marker (the console interleaves the
            # host's output with the ULP's), so a parsed status is a convenience, never the authority. The authority is
            # the machine's STATE (HERE/LATEST/entry) for success and the host's named refusal for failure.
            return status_of(reply), reply

        # --- T1 adopt + EXECUTE the returned entry
        st, rep = load()
        adopted = [d.num(f"z{i} @ .") for i in range(1, 7)]
        got_entry = d.num("W @ .")
        for i in range(1, 7):
            d.cmd(f"0 z{i} !")
        d.cmd("W @ EXECUTE", timeout=15.0)
        ran = [d.num(f"z{i} @ .") for i in range(1, 7)]
        ok1 = "adopted" in rep and got_entry == entry and adopted == cells0 and ran == [6712, 353000, 0, 57, 128, 38]
        print(f"  T1 adopt+execute      : {'PASS' if ok1 else 'FAIL'}  status {st.split()[-1]}, entry {got_entry}, "
              f"after EXECUTE {ran}")

        # --- T2 block count
        nblocks = int(re.search(r"-> (\d+) blocks", dump).group(1))
        print(f"  T2 block count        : {'PASS' if nblocks < len(blocks) else 'FAIL'}  image {nblocks} < source {len(blocks)}")

        # --- T3 fifty load/drop cycles: after each REWIND the pointers are the sealed ones; after each ADOPT they are
        # the image's. GUARDRAIL: the sealed check must be made after the rewind and before the load - reading HERE
        # after an adoption legitimately returns the image end, and an earlier version of this test failed for that
        # reason while the machine was behaving correctly.
        ok3 = True; why3 = ""
        for cyc in range(50):
            d.cmd("2 OVL")
            if d.num("HERE bh @ - .") != 0 or d.num("LATEST bl @ - .") != 0:
                ok3 = False; why3 = f"cycle {cyc}: rewind did not restore the sealed pointers"; break
            st3, rep3 = load()
            if "REFUSED" in rep3 or d.num("HERE .") != ce or d.num("LATEST .") != hs or d.num("W @ .") != entry:
                ok3 = False
                why3 = (f"cycle {cyc}: status {st3}, HERE {d.num('HERE .')} (want {ce}), "
                        f"LATEST {d.num('LATEST .')} (want {hs}), entry {d.num('W @ .')} (want {entry})")
                break
        print(f"  T3 50 load cycles     : {'PASS' if ok3 else 'FAIL  ' + why3}")

        # --- T4 corrupt one image byte -> named refusal, nothing adopted
        d.cmd(f"#p {DESC} 24 255")
        st4, rep4 = load()
        ok4 = ("REFUSED" in rep4 and "corrupt" in rep4)
        print(f"  T4 corrupt payload    : {'PASS' if ok4 else 'FAIL'}  status {st4}")

        # --- T5 stale resident checksum -> named refusal (forge the descriptor's resident sum)
        d.cmd(f"#d {DESC} {cs} {ce} {hs} {he} {entry}", timeout=20.0)
        d.cmd(f"#p {DESC} 13 0"); d.cmd(f"#p {DESC} 14 0")
        st5, rep5 = load()
        ok5 = ("REFUSED" in rep5 and "resident" in rep5)
        print(f"  T5 resident changed   : {'PASS' if ok5 else 'FAIL'}  status {st5}")

        # --- T6 image header shadowing a resident hash -> named refusal (forge the header AND fix the image sum)
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
        st6, rep6 = load()
        ok6 = ("REFUSED" in rep6 and "collision" in rep6)
        print(f"  T6 header collision   : {'PASS' if ok6 else 'FAIL'}  status {st6}")

        # --- T7 wrong sealed pointers -> named refusal (descriptor claims a seal 2 bytes off)
        d.cmd(f"#d {DESC} {cs} {ce} {hs} {he} {entry}", timeout=20.0)
        d.cmd(f"#p {DESC} 7 {(cs + 2) & 0xFF}"); d.cmd(f"#p {DESC} 8 {((cs + 2) >> 8) & 0xFF}")
        st7, rep7 = load()
        ok7 = ("REFUSED" in rep7 and "sealed pointers" in rep7)
        print(f"  T7 sealed pointers    : {'PASS' if ok7 else 'FAIL'}  status {st7}")

        # --- T8 the BLK_SZ(256) vs blk_sz(128) regression: payload bytes past offset 128 must survive
        d.cmd(f"#d {DESC} {cs} {ce} {hs} {he} {entry}", timeout=20.0)
        bad = 0
        for off in (0, 127, 128, 300, 500):
            mem = d.num(f"bh @ {off} + C@ .")
            g = 20 + off
            img = d.num(f"{DESC + g // 128} BLOCK {g % 128} + C@ .")
            if mem != img:
                bad += 1
        ok8 = bad == 0
        print(f"  T8 payload past 128   : {'PASS' if ok8 else 'FAIL'}  {5 - bad}/5 offsets byte-exact")

        fails = [] if all([ok1, nblocks < len(blocks), ok3, ok4, ok5, ok6, ok7, ok8]) else ["see above"]
        print(f"  result: {'8/8 pass' if not fails else 'FAILED ' + str(fails)}")
        return 0 if not fails else 1


sys.exit(main())
