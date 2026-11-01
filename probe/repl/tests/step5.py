#!/usr/bin/env python3
"""step5.py — STEP 5 items, plus the depth probe the earlier steps lacked.

Depth probe: push `1` one line at a time until the machine reports ERR_STACK, then depth = SD + 1 - k with SD = 16
(src/uforth.c). Overflow is the only stack condition that is LOUD here; underflow silently wraps and yields 0, which is
why every `.`-drain printed zeros for ever.

GUARDRAIL: a parser that relies on underflow cannot be validated anywhere on this machine. The drain parser is therefore
tested on a KNOWN stack (push 1 2 3, pop exactly three, check the order 3,2,1) - item 0 - and depth is measured by
overflow counting, never by popping past the bottom.
"""
import sys, re, pathlib, subprocess, statistics, time
sys.path.insert(0, "tools")
from devio import Dev
sys.path.insert(0, "tests")
from step4 import phase_src, host_expect, build_and_adopt, IMG_AREA, DATA, PAT

SD = 16
wd = pathlib.Path(".auto/tmp")


def depth(d):
    """Depth of the data stack, by pushing until overflow. Leaves the stack cleared by the error path.

    GUARDRAIL: the push must go through a DISPATCH. `interpret()`'s literal branch calls PUSH directly, and the overflow
    report lives in the primitive dispatch tail (src/uforth.c `tail:`), so literals overflow SILENTLY - measured as a
    probe that reported "no overflow at all" on a known 3-cell stack. `P` is a one-line colon word, so each `P` is a
    dispatch and the report fires.
    """
    d.cmd(": P 1 ;")
    for k in range(1, SD + 3):
        if "ERR_STACK" in d.cmd("P", timeout=8.0):
            return SD + 1 - k
    return None


def pop_n(d, n):
    """Pop exactly n values (top first). Safe because n is known: no underflow is relied on."""
    vals = []
    for _ in range(n):
        out = d.cmd(".", timeout=8.0)
        if "ERR_STACK" in out:
            break
        nums = Dev.nums(out)
        if not nums:
            break
        vals.append(nums[-1])
    return vals


def host_dry():
    blocks = phase_src(1)
    bf = wd / "s5.blocks"
    bf.write_text("".join(f"{8+k} {b.encode().hex()}\n" for k, b in enumerate(blocks))
                  + f"2 {(' '*128).encode().hex()}\n" + f"{DATA(1)} {PAT(1).encode().hex()}\n")
    # known stack, pop exactly three, then measure depth by overflow
    # GUARDRAIL: the host loader has NO per-command framing - `.` prints digits with no separator, so three pops arrive
    # as "321". Every pop therefore emits a trailing space (`32 EMIT`), which works identically on the framed device.
    lines = ["1 2 3", ". 32 EMIT", ". 32 EMIT", ". 32 EMIT"] + ["1"] * 20
    dr = wd / "s5.fs"
    dr.write_text("\n".join(lines) + "\n")
    raw = subprocess.run(["artifacts/host_blk", "-B", str(bf), "-k", "src/p39_prelude.fs",
                          "src/p39b_overlay.fs", str(dr)], capture_output=True).stdout
    # GUARDRAIL: the host build emits engine errors as CODES; without `expand` the transcript never contains the text
    # "ERR_STACK" and the depth probe reported "no overflow at all".
    exp = subprocess.run(["./artifacts/expand"], input=raw, capture_output=True)
    out = exp.stdout.decode("latin-1")
    nums = Dev.nums(out)
    order_ok = nums[:3] == [3, 2, 1]
    # after the three pops the depth is 0; the first push that overflows is the 16th, so 15 successes then ERR_STACK
    k = next((i for i, ln in enumerate(out.splitlines()) if "ERR_STACK" in ln), None)
    print(f"  known-stack parser: popped {nums[:3]} (want [3,2,1]) -> {'PASS' if order_ok else 'FAIL'}")
    print(f"  depth probe on the host: overflow line index {k} (expected after 16 pushes from depth 0)")
    return 0 if order_ok else 1


def item1():
    """15-cycle dump/adopt loop (with the BLKXFER DROP fix), then depth 0 and first popped value 0 (never 1808)."""
    with Dev() as d:
        d.cmd("0 BLOCK CONSTANT W")
        # positive control for the depth probe on a KNOWN stack: three pushes must read back as depth 3
        d.cmd("7 8 9")
        ctl = depth(d)
        print(f"  depth-probe control on a known 3-cell stack: {ctl} (want 3)")
        if ctl != 3:
            print("  depth probe is not trustworthy - stopping rather than reporting item 1")
            return 1
        for p in range(1, 16):
            ok, got, note = build_and_adopt(d, p, IMG_AREA + (p - 1) * 5, phase_src(p))
            if not ok:
                print(f"  cycle {p}: FAILED {note}"); return 1
        dp = depth(d)
        first = pop_n(d, 1)
        print(f"  item1 loop: 15/15 cycles OK | stack depth after loop = {dp} (want 0) | first popped {first} "
              f"(want [0], never [1808])")
        return 0 if dp == 0 and first == [0] else 1


def item2_3():
    """All 15 phases from BINARY images with per-phase signatures, then 200 timed loads."""
    exp = {p: host_expect(p, wd) for p in range(1, 16)}
    bad = []
    times = []
    with Dev() as d:
        d.cmd("0 BLOCK CONSTANT W")
        # positive control for the depth probe on a KNOWN stack: three pushes must read back as depth 3
        d.cmd("7 8 9")
        ctl = depth(d)
        print(f"  depth-probe control on a known 3-cell stack: {ctl} (want 3)")
        if ctl != 3:
            print("  depth probe is not trustworthy - stopping rather than reporting item 1")
            return 1
        for p in range(1, 16):
            ok, got, note = build_and_adopt(d, p, IMG_AREA + (p - 1) * 5, phase_src(p))
            if not (ok and got == exp[p]):
                bad.append((p, got, exp[p]))
            print(f"  phase {p:2d} via BINARY image (op 3): {'PASS' if ok and got == exp[p] else 'FAIL'} {got}")
        for _ in range(200):
            d.cmd("2 OVL")
            t0 = time.monotonic()
            d.cmd(f"{IMG_AREA} 3 BLKXFER . DROP", timeout=25.0)
            times.append((time.monotonic() - t0) * 1000)
    times.sort()
    print(f"  item2: {15 - len(bad)}/15 phases executed from images" + (f" FAILED {bad[:2]}" if bad else ""))
    print(f"  item3 apply round trip x200: min {times[0]:.1f}  median {statistics.median(times):.1f}  "
          f"max {times[-1]:.1f} ms")
    print(f"  item3 proposed age bound = ULP wait 845 - worst {times[-1]:.1f} - margin 200 = "
          f"{845 - times[-1] - 200:.0f} ms   (current 400 ms NOT changed)")
    return 0 if not bad else 1


def all_items():
    """Items 1+2+3 in ONE chip session, because the probe needed two failed attempts to get its instrument right."""
    exp = {p: host_expect(p, wd) for p in range(1, 16)}
    with Dev() as d:
        d.cmd("0 BLOCK CONSTANT W")
        d.cmd("7 8 9")
        ctl = depth(d)
        print(f"  depth-probe control on a known 3-cell stack: {ctl} (want 3)")
        # --- item 1
        okall = True
        for p in range(1, 16):
            ok, got, note = build_and_adopt(d, p, IMG_AREA + (p - 1) * 5, phase_src(p))
            if not ok:
                print(f"  item1 cycle {p}: FAILED {note}"); okall = False; break
        dp = depth(d)
        first = pop_n(d, 1)
        print(f"  item1: loop {'15/15' if okall else 'FAILED'} | depth after loop {dp} (want 0) | "
              f"first popped {first} (want [0], never 1808)")
        # --- item 2 (signatures) + item 3 (timing), same session
        bad = []
        for p in range(1, 16):
            ok, got, note = build_and_adopt(d, p, IMG_AREA + (p - 1) * 5, phase_src(p))
            if not (ok and got == exp[p]):
                bad.append((p, got, exp[p]))
        print(f"  item2: {15-len(bad)}/15 phases via BINARY image (op 3) matched their host run"
              + (f" FAILED {bad[:2]}" if bad else ""))
        times = []
        for _ in range(200):
            d.cmd("2 OVL")
            t0 = time.monotonic()
            d.cmd(f"{IMG_AREA} 3 BLKXFER . DROP", timeout=25.0)
            times.append((time.monotonic() - t0) * 1000)
        times.sort()
        print(f"  item3 apply x200: min {times[0]:.1f} median {statistics.median(times):.1f} "
              f"max {times[-1]:.1f} ms | proposed bound {845 - times[-1] - 200:.0f} ms (400 NOT changed)")
    return 0 if (ctl == 3 and dp == 0 and first == [0] and not bad) else 1


if __name__ == "__main__":
    sys.exit({"dry": host_dry, "1": item1, "23": item2_3, "all": all_items}[sys.argv[1]]() or 0)
