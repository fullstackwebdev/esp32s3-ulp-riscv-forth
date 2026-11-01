#!/usr/bin/env python3
"""dispatcher.py — the dispatcher-only launcher: how big the phase window really is, and how far a chain runs.

This formalises a throwaway probe. It answers two questions with numbers instead of opinions:

  1. **How much window is left when only the dispatcher is resident?** `examples/boot.fs` defines the chain machinery
     (`CHAIN`/`PICKX`/`SWITCH`/`GO` + two cells) and nothing else. Measured: seal 926-932, sealed LATEST 2128, so the
     window is **~1 195 B** against **254 B** for the full menu launcher — 4.7x.
  2. **How many hops can a chain actually take?** It builds N generated phases (each bumps a resident cell and names the
     next), runs the chain, and requires the counter to equal N and the line to RETURN.

GUARDRAIL: the hop cost is now ~2.1 ms and nothing in the launcher waits for it. It used to be 30.8 ms with a 20 ms
"hop gap", because the HP serviced a block request only on a 0->1 EDGE it sampled once per FreeRTOS tick, and a raw
BLKXFER does not raise `repl_blk_req` - so an ULP that cleared and re-raised the flag between two polls was never
serviced (845 ms BLKWAIT, BK_NOSERVER, flag left set, everything after that BK_BUSY). Three changes removed the gap:
the HP now tests the PENDING LEVEL (blk_out == 1 AND mailbox[2] == 0), which no poll gap can miss; the ULP publishes
`blk_out` AFTER the mailbox, so a half-posted request cannot be seen; and after servicing, the HP keeps polling for
8 x 150 us (`hot`) instead of sleeping a whole 10 ms tick, because a chained phase asks again ~100-300 us later.
Do not reintroduce a fixed gap: it hid the level bug for hours and costs more than the transfer itself.

GUARDRAIL: phase names must not collide with a RESIDENT name - the dictionary stores a 12-bit hash and refuses a
collision with the same `NAME?` a missing word produces. `: P1` was refused while `: PHASE1` compiled. With ~60 resident
words the per-name odds are ~2-3 %; a paged design multiplies the number of names, so this grows teeth.
"""
import os, sys, time, select, pathlib, re

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "probe" / "repl" / "tools"))

PORT = os.environ.get("PORT_DEV", "/dev/ttyACM1")
HOPS = 24
BOOT_FIRST = 100          # the dispatcher lives high so the phase images can start low
PHASE_FIRST = 30          # each phase takes 2 blocks: 30, 32, ... 76  (the store has 128)


def main():
    import cli
    dev = cli.connect(PORT, 1.0)
    if not dev:
        return 2
    results, scratch = [], ROOT / "probe" / "repl" / ".dispatcher_phase.fs"

    def check(name, ok, note=""):
        results.append((name, ok, note))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<42} {note}")

    try:
        n, bad = cli.upload(dev, str(ROOT / "examples/boot.fs"), BOOT_FIRST)
        if bad:
            raise SystemExit(f"examples/boot.fs did not compile: {bad}")
        dev.cmd("SEAL")
        seal, latest = dev.num("bh @ ."), dev.num("bl @ .")
        window = latest - seal
        check("the dispatcher fits in the high store and seals", n == 5, f"{n} blocks, seal {seal}")
        check("a dispatcher-only launcher leaves a big window", window > 1000,
              f"window {window} B (menu launcher today: 254 B)")

        descs = [PHASE_FIRST + 2 * i for i in range(HOPS)]
        assert descs[-1] + 1 < BOOT_FIRST, "phase images would overlap the dispatcher"
        code = 0
        for i, desc in enumerate(descs):
            nxt = descs[i + 1] if i + 1 < len(descs) else 0
            scratch.write_text(": PHASE%d ( -- ) PA @ 1+ PA ! %d CHAIN ;\n" % (i + 1, nxt))
            dev.cmd("RW", timeout=5.0)
            n, bad = cli.upload(dev, str(scratch), 20)
            if bad:
                raise SystemExit(f"phase {i + 1} did not compile: {bad}")
            cs, ce = dev.num("bh @ ."), dev.num("HERE .")
            hs, he = dev.num("LATEST ."), dev.num("bl @ .")
            ent = dev.num("' PHASE%d ." % (i + 1))
            code = ce - cs
            dev.cmd("#d %d %d %d %d %d %d" % (desc, cs, ce, hs, he, ent))
        check(f"{HOPS} phases built, {code} B each", True, f"blocks {descs[0]}..{descs[-1] + 1}")

        dev.cmd("RW")
        t0 = time.time()
        os.write(dev.fd, b"%d GO\r" % descs[0])
        buf, end = b"", time.time() + 30
        while time.time() < end and b" ok" not in buf:
            r, _, _ = select.select([dev.fd], [], [], 0.05)
            if r:
                try:
                    buf += os.read(dev.fd, 8192)
                except OSError:
                    break
        ms = (time.time() - t0) * 1000
        check(f"a chain of {HOPS} hops RETURNS", b" ok" in buf, f"{ms:.0f} ms, {ms / HOPS:.1f} ms/hop")
        # GUARDRAIL: assert the LATENCY, not just the outcome. It was 30.8 ms/hop behind a 20 ms launcher gap and nobody
        # noticed, because "the chain works" was the only thing tested. 8 ms is ~4x the measured 2.1 ms: a real regression
        # (a tick wait reappearing, the per-adopt printf coming back) fails here instead of being felt by a user.
        check("a hop costs less than 8 ms", ms / HOPS < 8.0, f"{ms / HOPS:.1f} ms/hop")
        got = dev.num("PA @ .")
        check(f"every phase ran, in order ({HOPS})", got == HOPS, f"counter {got}")
        hits = re.findall(rb"REFUSED \w+|ERR_BUSY|ERR_", buf)
        check("no adopt was refused or busy", not hits, str(hits[:3]) if hits else "none")
    finally:
        if scratch.exists():
            scratch.unlink()
        dev.close()
    bad = sum(1 for _, ok, _ in results if not ok)
    print(f"\n  {len(results) - bad}/{len(results)} checks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
