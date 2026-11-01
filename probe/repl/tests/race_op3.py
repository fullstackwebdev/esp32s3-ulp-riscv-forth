#!/usr/bin/env python3
"""race_op3.py — does the host apply an image the ULP has already given up on?

Provokes the race deterministically: `#s 800` stalls the block task for 800 ms, longer than the ULP's BLKWAIT budget
(~0.2-0.4 s), so `n 3 BLKXFER` returns BK_NOSERVER (-3). Then it waits and asks whether the image was applied anyway.

The correct answer is NO: the ULP believes the load failed, so nothing may be adopted. A host that services whatever
`blk_out` advertises will apply it late - silently adopting a dictionary the machine was told it does not have.
"""
import sys, re, pathlib, time
sys.path.insert(0, "tools")
from devio import Dev
from fsplit import split_defs

DESC = 40


def main():
    src = " ".join(re.sub(r"\([^)]*\)", "", re.sub(r"\\.*", "", pathlib.Path("tests/ph1.fsx").read_text())).split())
    blocks = split_defs(src, 128)
    blocks[-1] = blocks[-1].rstrip()[: -len("RUNPH1")].rstrip()
    with Dev() as d:
        d.seed_many([(2, " " * 128), (4, " " * 128)] + [(8 + k, b) for k, b in enumerate(blocks)])
        d.cmd("0 BLOCK CONSTANT W")
        d.cmd("SEAL"); d.cmd("2 OVL")
        for k in range(len(blocks)):
            d.cmd(f"{8+k} LOAD", timeout=10.0)
        cs, ce = d.num("bh @ ."), d.num("HERE .")
        hs, he = d.num("LATEST ."), d.num("bl @ .")
        entry = d.num("' RUNPH1 .")
        d.cmd(f"#d {DESC} {cs} {ce} {hs} {he} {entry}", timeout=20.0)
        d.cmd("2 OVL")
        print(f"  before: ' RUNPH1 =", d.cmd("' RUNPH1 .").strip().splitlines()[-1])
        # GUARDRAIL: the ULP's BLKWAIT is 2 000 000 iterations, measured at ~845 ms on hardware - an 800 ms stall let
        # the answer arrive in time (status 0), so the race was never provoked. The stall must exceed the wait.
        print("  ", d.cmd("#s 3000", timeout=10.0).strip().splitlines()[-1])
        t0 = time.monotonic()
        raw = d.cmd(f"{DESC} 3 BLKXFER .", timeout=20.0)
        st = str(Dev.nums(raw)[-1]) if Dev.nums(raw) else raw.strip()
        dt = (time.monotonic() - t0) * 1000
        print(f"  op 3 status {st} (after {dt:.0f} ms - the ULP gave up)")
        time.sleep(2.0)                                   # give a naive host time to apply it late
        # GUARDRAIL: read the WHOLE reply. On the naive host the transcript also carries the host's "img: REFUSED
        # sealed pointers moved" line (the second, repeated service of the same stale request), so taking the last line
        # picks up the host's message instead of the value and reads as "not raced" when it did race.
        # GUARDRAIL: the verdict is the machine's STATE, not a parsed transcript: after the ULP gave up, HERE must
        # still be the sealed base (nothing adopted). Reading "RUNPH1?" out of the console was unreliable because the
        # host's own refusal line and the ULP's reply interleave.
        after = d.cmd("' RUNPH1 .", timeout=15.0)
        flat = " ".join(x.strip() for x in after.splitlines() if x.strip())
        here = d.num("HERE .")
        applied = here != cs
        print(f"  after 2 s: HERE {here} (sealed {cs}) | {flat[:90]}")
        raced = applied
        if st != "-3":
            print(f"  INCONCLUSIVE: the ULP did not time out (status {st}); the stall must exceed BLKWAIT")
            return 2
        print(f"  RACE: {'REPRODUCED (image applied after the ULP timed out)' if raced else 'not reproduced (nothing applied)'}")
        return 1 if raced else 0          # exit 1 = the bad outcome, so the naive build visibly fails this test


sys.exit(main())
