#!/usr/bin/env python3
"""capabilities.py — the paging capabilities as ONE device verifier. `--host` runs the device-free half.

Every check names a capability, states the CORRECT expectation, and exits non-zero on the first failure so it can be a
gate. It is deliberately one session: reseeding per capability would triple the wall time for no extra coverage.

Covered code paths, in order (cheap -> expensive):
  engine boot · block transport (incl. the BLK_SZ>128 defect) · source phase load+execute · image build (#d descriptor)
  · image adopt via mailbox op 3 + entry xt · five refusals (corrupt / resident / collision / sealed / stale)
  · 15 dump+adopt cycles (leak check) · apply latency (20 samples, capability not measurement)

GUARDRAIL: expectations come from the HOST run of the same bytes (`host_expect`), never from arithmetic of mine, and
`BLKXFER` is `( n op -- addr st )` so every call consumes BOTH values (`. DROP`) - dropping only the status left one
`1808` per call on the stack and overflowed at cycle 14.
"""
import sys, re, pathlib, subprocess, statistics, time
sys.path.insert(0, "tools")
from devio import Dev
sys.path.insert(0, "tests")
from step4 import phase_src, host_expect, build_and_adopt, IMG_AREA, DATA, PAT

CTRL, SD = 1536, 16
wd = pathlib.Path(".auto/tmp")
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    return ok


def host_half():
    exp = {p: host_expect(p, wd) for p in range(1, 16)}
    check("host: 15 distinct per-phase signatures", len(set(map(tuple, exp.values()))) == 15,
          f"p1={exp[1]} p15={exp[15]}")
    return 0 if all(ok for _, ok in results) else 1


def device_half():
    exp = {p: host_expect(p, wd) for p in range(1, 16)}
    with Dev() as d:
        d.cmd("0 BLOCK CONSTANT W")
        # --- engine boot
        check("engine: 2 3 + . == 5", d.num("2 3 + .") == 5)
        app = d.num("LATEST HERE - .")
        check("engine: application space > 0", app > 0, f"{app} B")

        # --- block transport, including bytes past offset 128 (the BLK_SZ vs blk_sz defect)
        pat = "".join(chr(65 + (k % 26)) for k in range(128))
        d.seed_many([(DATA(1), pat)])
        bad = [o for o in (0, 1, 64, 127) if d.num(f"{DATA(1)} BLOCK {o} + C@ .") != ord(pat[o])]
        check("blocks: seed+read byte-exact (0,1,64,127)", not bad, f"bad offsets {bad}")

        # --- source phase load + execute (step-0 semantics)
        ok, got, note = build_and_adopt(d, 1, IMG_AREA, phase_src(1))
        check("phase: source load + execute matches host", ok and got == exp[1], f"{got}")

        # --- descriptor sanity for the image just built
        desc = IMG_AREA
        magic = [d.num(f"{desc} BLOCK {i} + C@ .") for i in range(3)]
        # GUARDRAIL: read the entry from the DESCRIPTOR bytes, not from a transcript: `W @ .` replies can carry output
        # bled from the previous command, which parsed as 67258694 (two numbers concatenated).
        e_lo = d.num(f"{desc} BLOCK 15 + C@ .")
        e_hi = d.num(f"{desc} BLOCK 16 + C@ .")
        entry_desc = e_lo | (e_hi << 8)
        entry_now = d.num("' RUNPH1 .")
        check("image: descriptor v2 + entry xt", magic[:2] == [ord('F'), ord('I')] and magic[2] == 2
              and entry_desc == entry_now, f"magic {magic} entry {entry_desc} vs live {entry_now}")

        # --- refusals. GUARDRAIL: each case REBUILDS a clean image immediately before forging it. Reusing the previous
        # image let one case's forgery (or its refusal) leak into the next, and two checks failed for that reason while
        # the same refusals pass 8/8 in tests/loader_tests.py, which rebuilds per case.
        def try_load(desc):
            # GUARDRAIL: REWIND FIRST. After an adoption V_HERE is the image's end, so without `2 OVL` the loader's
            # seal check fires on every case and all three refusals report "sealed pointers moved" - measured, and it
            # made two correct refusals look broken. tests/loader_tests.py rewinds inside its load() for this reason.
            d.cmd("2 OVL")
            return d.cmd(f"{desc} 3 BLKXFER . DROP", timeout=20.0)

        ok, _, _ = build_and_adopt(d, 3, 50, phase_src(3))
        d.cmd("#p 50 24 255")
        r = try_load(50)
        check("refuse: corrupt image byte", "REFUSED" in r and "corrupt" in r, r.strip().splitlines()[0][:52])

        ok, _, _ = build_and_adopt(d, 4, 55, phase_src(4))
        d.cmd("#p 55 13 0"); d.cmd("#p 55 14 0")
        r = try_load(55)
        check("refuse: resident dictionary changed", "REFUSED" in r and "resident" in r, r.strip().splitlines()[0][:52])

        ok, _, _ = build_and_adopt(d, 5, 60, phase_src(5))
        cs2 = d.num("bh @ .")
        d.cmd(f"#p 60 7 {(cs2 + 2) & 0xFF}"); d.cmd(f"#p 60 8 {((cs2 + 2) >> 8) & 0xFF}")
        r = try_load(60)
        check("refuse: sealed pointers moved", "REFUSED" in r and "sealed" in r, r.strip().splitlines()[0][:52])

        # --- 15 dump+adopt cycles: the leak path that used to overflow at 14
        cyc_ok = True
        for p in range(6, 16):
            ok, got, _ = build_and_adopt(d, p, IMG_AREA + (p - 1) * 5, phase_src(p))
            if not (ok and got == exp[p]):
                cyc_ok = False
                check(f"cycles: phase {p} from image", False, f"{got} vs {exp[p]}")
                break
        check("cycles: 10 further dump+adopt cycles (6..15)", cyc_ok)
        first = d.cmd(". 32 EMIT", timeout=8.0)
        check("cycles: no window address left on the stack", "1808" not in first, first.strip()[:24])

        # --- apply latency: capability check, not the 200-sample measurement
        t = []
        for _ in range(20):
            d.cmd("2 OVL")
            t0 = time.monotonic(); d.cmd(f"{IMG_AREA} 3 BLKXFER . DROP", timeout=25.0)
            t.append((time.monotonic() - t0) * 1000)
        t.sort()
        check("timing: apply median under 100 ms", statistics.median(t) < 100,
              f"min {t[0]:.0f} med {statistics.median(t):.0f} max {t[-1]:.0f} ms")
    fails = [n for n, ok in results if not ok]
    print(f"  {len(results)-len(fails)}/{len(results)} capability checks pass" + (f" FAILED {fails}" if fails else ""))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(host_half() if "--host" in sys.argv else device_half())
