#!/usr/bin/env python3
"""adopt_sum.py — the resident-identity guard: what it must ignore, and what it must still refuse.

History this file exists to settle. docs/25 recorded the second adopt as refused with
`img: REFUSED resident dictionary changed` and *hypothesised* that the checksum's tail `[sealed LATEST, top)` is
rewritten by the adopt itself. Measured here, on the device, that hypothesis was wrong:

    after `#d 50`                      [52,1666) 46340   [2032,2476) 55781   total 36585
    adopt 50, adopt 50, adopt 60       [52,1666) 46340   [2032,2476) 55781   total 36585
    `1 SEL !`  (what pressing k does)  [52,1666) 46341   [2032,2476) 55781   total 36586  <- REFUSED

The header area never moved. `[52, cs)` — the resident code region — holds the launcher's LIVE cells (`SEL`, `q`,
`qh`, `qt`, `bh`, `bl`, ...), and the menu writes `SEL` on every toggle. So the guard was refusing a dictionary
that had not changed, on ordinary use. The range is now the header area alone: 3-byte entries are
`imm1 | xt11 | hash12`, so it still pins every resident name and every xt the image will call — the only mismatch
that makes an adopt execute garbage.

This file asserts BOTH directions, because a guard nobody can trip is not a guard:
  1. adopting the same image twice, then a different image, all succeed;
  2. a plain `SEL` write changes no sum and blocks nothing;
  3. a FORGED resident sum (`#p` on the descriptor's own field) is still REFUSED, by name.

GUARDRAIL: drive adoption with `<desc> 3 BLKXFER` from the REPL, not through the launcher's menu. The menu needs
`!RAW`, and in raw mode the keybox eats `HERE .` as a keystroke, so the machine cannot be inspected at the moment it
refuses — that is why programs.py grew dump_state(). BLKXFER from the REPL is the same op 3 the launcher issues
(`SWITCH` is `RW 3 BLKXFER DROP @ EXECUTE`), with the machine left readable afterwards.

GUARDRAIL: `RW` (the launcher's own pure rewind, `bh @ VH ! bl @ VL !`) after every adopt. An adopt leaves V_HERE at
the image's end, so without the rewind the next upload compiles above the image and every later address is wrong.
"""
import os, re, sys, pathlib

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "probe" / "repl" / "tools"))

MENU_FIRST = 70
DEMO_FIRST = 30
BARS_DESC, OTHER_DESC = 40, 60   # bars, and the gauge's first phase
PORT = os.environ.get("PORT_DEV", "/dev/ttyACM1")


def cells(dev, a, n):
    rep = dev.cmd(f"#m {a} {n}", timeout=5.0)
    line = [l for l in rep.splitlines() if l.startswith("mem:")]
    if not line:
        raise RuntimeError(f"#m {a} {n} answered nothing usable: {rep!r}")
    got = {}
    for m in re.finditer(r"\[(\d+)\]=(\d+)", line[0]):
        got[int(m.group(1))] = int(m.group(2))
    if len(got) != n:
        raise RuntimeError(f"#m {a} {n} returned {len(got)} of {n} cells: {rep!r}")
    return got


def dump(dev, lo, hi):
    """Bytes of mem[] in [lo, hi). 16 cells per command (#m's cap); a partial tail is read as one more cell pair."""
    buf = {}
    a = lo
    while a < hi:
        n = min(16, (hi - a + 1) // 2)
        if n == 0:
            n = 1
        for k, v in cells(dev, a, n).items():
            buf[k] = v & 0xff
            buf[k + 1] = (v >> 8) & 0xff
        a += n * 2
    return buf


def ssum(buf, lo, hi):
    return sum(buf.get(i, 0) for i in range(lo, hi)) & 0xffff


def diff(a, b, lo, hi):
    return [i for i in range(lo, hi) if a.get(i) != b.get(i)]


def blk_off(dev):
    rep = dev.cmd("#u", timeout=5.0)
    m = re.search(r"blk_out \d+ req \d+ off (\d+) sz (\d+)", rep)
    if not m:
        raise RuntimeError(f"#u answered without the blk window: {rep!r}")
    return int(m.group(1)), int(m.group(2))


def adopt(dev, desc):
    """op 3 exactly as SWITCH issues it. BLKXFER is ( n op -- addr st ); the transcript is kept, not guessed."""
    rep = dev.cmd(f"{desc} 3 BLKXFER SWAP DROP .", timeout=25.0, allow_error=True)
    st = None
    for line in rep.splitlines():
        if "REFUSED" in line or "adopted" in line:
            print(f"    device: {line.strip()}")
        if re.fullmatch(r"-?\d+ ok", line.strip()):
            st = int(line.strip().split()[0])
    if st is None:
        raise RuntimeError(f"adopt {desc}: no status in the reply {rep!r}")
    return st


def main():
    import cli
    dev = cli.connect(PORT, 1.0)
    if not dev:
        return 1
    results = []
    seen = {}

    def check(name, ok, text=""):
        results.append((name, ok, text))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<44} {text}")

    def snap(tag):
        buf = dump(dev, 52, top)
        seen[tag] = buf
        hdr = ssum(buf, vseal, top)
        print(f"  {tag:<40} headers [{vseal},{top}) sum {hdr:5d}   [52,{cs}) sum {ssum(buf, 52, cs):5d}")
        return hdr

    try:
        top, blk_sz = blk_off(dev)
        print(f"  fresh: HERE {dev.num('HERE .')} LATEST {dev.num('LATEST .')} | mem top {top}, transfer {blk_sz} B")

        n, bad = cli.upload(dev, str(ROOT / "examples/menu.fs"), MENU_FIRST)
        if bad:
            raise SystemExit(f"launcher did not compile: {bad}")
        dev.cmd("SEAL", timeout=5.0)
        cs, vseal = dev.num("bh @ ."), dev.num("bl @ .")
        print(f"  launcher sealed: cs {cs}, sealed LATEST {vseal}, header area {top - vseal} B")
        check("header area exists above the seal", vseal < top, f"{vseal} < {top}")

        built = {}
        for path, desc, entry in (("examples/demo_bars.fs", BARS_DESC, "RUNB"),
                                  ("examples/gauge1.fs", OTHER_DESC, "GAUGE1")):
            dev.cmd("RW", timeout=5.0)
            n, bad = cli.upload(dev, str(ROOT / path), DEMO_FIRST)
            if bad:
                raise SystemExit(f"{path} did not compile: {bad}")
            ce, hs = dev.num("HERE ."), dev.num("LATEST .")
            ent = dev.num(f"' {entry} .")
            check(f"{pathlib.Path(path).name}: compiled above the seal", cs == dev.num("bh @ .") and ce > cs,
                  f"code {cs}..{ce} ({ce - cs} B), LATEST {hs}, entry {ent}")
            dev.cmd(f"#d {desc} {cs} {ce} {hs} {vseal} {ent}", timeout=20.0)
            built[desc] = dict(ce=ce, hs=hs)
            built[desc]["hdr_sum"] = snap(f"after #d {desc}")
        dev.cmd("RW", timeout=5.0)
        check("both images carry the SAME resident identity", len({b["hdr_sum"] for b in built.values()}) == 1,
              " / ".join(str(b["hdr_sum"]) for b in built.values()) + " (one launcher, one identity)")

        # GUARDRAIL: pin the digits, not just "a number appeared". `.N` shipped printing "09" for 9 (the single-digit
        # test was `DUP 9 <`, which is false at 9), and every device test passed because none of them read the text.
        for n, want in ((0, "0"), (9, "9"), (42, "42"), (99, "99"), (100, "0")):
            rep = dev.cmd(f"{n} .N", timeout=5.0, allow_error=True)
            got = [l for l in rep.splitlines() if l.strip().endswith("ok")]
            # GUARDRAIL: strip the space the printer puts before `ok` - the transcript is "<digits> ok", and an
            # unstripped compare reports a failure for every correct digit (measured: five FALSE failures).
            have = got[-1].rsplit("ok", 1)[0].strip() if got else ""
            check(f".N prints {n} as {want!r}", have == want, f"got {have!r}")

        for i, (desc, note) in enumerate(((BARS_DESC, "first"), (BARS_DESC, "same image again"),
                                          (OTHER_DESC, "a DIFFERENT image")), start=1):
            st = adopt(dev, desc)
            check(f"adopt #{i} ({note})", st == 0, f"block {desc}, status {st}")
            dev.cmd("RW", timeout=5.0)
        check("adopt leaves the identity untouched",
              ssum(dump(dev, 52, top), vseal, top) == built[BARS_DESC]["hdr_sum"])

        rep = dev.cmd(f"#c {OTHER_DESC}", timeout=10.0)
        line = [l for l in rep.splitlines() if l.startswith("cmp:")]
        check("#c agrees with mem[] after an adopt", bool(line) and " 0 byte(s) differ" in line[0],
              line[0].strip() if line else "no cmp line")

        sel = dev.num("SEL @ .")
        dev.cmd("1 SEL !", timeout=5.0)
        after_toggle = snap("after SEL 0->1 (the `k` key)")
        check("a live resident cell moves NO identity", after_toggle == built[BARS_DESC]["hdr_sum"],
              f"SEL {sel} -> {dev.num('SEL @ .')}, header sum {after_toggle}")
        st = adopt(dev, OTHER_DESC)
        check("adopt after the SEL write", st == 0, f"status {st} (this is the bug docs/25 recorded)")
        dev.cmd("RW", timeout=5.0)
        dev.cmd("0 SEL !", timeout=5.0)

        # A guard that cannot be tripped is not a guard: forge the identity it compares and require a named refusal.
        want = built[OTHER_DESC]["hdr_sum"]
        lo, hi = want & 0xff, (want >> 8) & 0xff
        dev.cmd(f"#p {OTHER_DESC} 13 {(lo + 1) & 0xff}", timeout=5.0)
        st = adopt(dev, OTHER_DESC)
        check("a FORGED identity is refused", st != 0, f"status {st} (nack 4 = BK_CRC)")
        dev.cmd(f"#p {OTHER_DESC} 13 {lo}", timeout=5.0)
        st = adopt(dev, OTHER_DESC)
        check("restoring the field makes it adopt again", st == 0, f"status {st}, descriptor {lo}/{hi}")

        moved = diff(seen[f"after #d {BARS_DESC}"], seen["after SEL 0->1 (the `k` key)"], 52, cs)
        print(f"\n  [52,{cs}) moved by {len(moved)} byte(s) on the SEL write"
              + (f" at {moved[:8]}" if moved else "") + " - exactly what the old range summed")
        check("that is real: the resident code region DOES hold live state", bool(moved),
              "if this ever stops being true the reasoning in resident_sum() must be re-measured")
    finally:
        dev.close()
    bad = sum(1 for _, ok, _ in results if not ok)
    print(f"\n  {len(results) - bad}/{len(results)} checks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
