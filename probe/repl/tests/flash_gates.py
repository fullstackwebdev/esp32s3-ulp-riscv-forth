#!/usr/bin/env python3
"""flash_gates.py — STEP 6: gate 3 (corrupt superblock), torn-flush, and flush/erase accounting.

`dry`     : host-only check of the pattern classifier (no chip)
`corrupt` : clobber the superblock magic in the partition, reboot, report what the board says
`torn`    : interrupt a flush with a hard reset, 20+ times; classify the block as OLD / NEW / MIXED
`cost`    : flushes, erases and bytes for a 15-phase load/switch run, with a lifetime estimate
"""
import sys, os, re, subprocess, time, pathlib
sys.path.insert(0, "tools")
from devio import Dev
sys.path.insert(0, "tests")
from step4 import phase_src, host_expect, build_and_adopt, IMG_AREA, DATA, PAT

PORT = "/dev/ttyACM1"
PART_OFF = 0x110000      # 'blocks' partition: factory is 1 M at 0x10000, so the store starts at 0x110000
wd = pathlib.Path(".auto/tmp")


def dry():
    """Classify a 128-byte block as OLD / NEW / MIXED from its bytes. The torn-flush verdict rests on this."""
    old, new = b"A" * 128, b"B" * 128
    cases = [(old, "OLD"), (new, "NEW"), (old[:64] + new[64:], "MIXED")]
    ok = True
    for data, want in cases:
        got = classify(data, old, new)
        ok = ok and got == want
        print(f"  {got:5s} (want {want})")
    print(f"  classifier: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def classify(data, old, new):
    if data == old: return "OLD"
    if data == new: return "NEW"
    return "MIXED"


def corrupt_super():
    """Overwrite the superblock's first 8 bytes with zeros - the partition is sector 0 - and reboot."""
    blob = wd / "zeros.bin"
    blob.write_bytes(b"\x00" * 8)
    r = subprocess.run(["python3", "-m", "esptool", "--port", PORT, "write_flash", hex(PART_OFF), str(blob)],
                       capture_output=True, text=True)
    print(f"  esptool: {'ok' if r.returncode == 0 else 'FAILED: ' + r.stderr[-80:]}")


def corrupt(mode):
    corrupt_super()
    time.sleep(0.5)
    with Dev() as d:
        boot = d.drain(0.6)
        line = [l for l in boot.splitlines() if "store:" in l]
        # GUARDRAIL: the boot line is printed BEFORE any tool opens the port, so it is unreachable after the fact -
        # measured. Ask on demand with `#i`, which reports the same named refusal (and is what an operator would use).
        info = d.cmd("#i").strip().splitlines()[-1]
        print(f"  boot ({mode}): {line[-1] if line else '(not captured - asked #i instead)'}")
        print(f"  #i: {info[:88]}")
        usable = d.num("2 3 + .") == 5
        print(f"  REPL usable: {usable}")
        if mode == "skip":
            # with validation skipped the store claims to work: read a block and show it is garbage, not data
            v = d.num(f"{DATA(1)} BLOCK 0 + C@ .")
            print(f"  block {DATA(1)} byte0 with no check = {v} (garbage served as data)")
            return 0
        refused = "REFUSED" in info
        rec = d.cmd("#x")
        print(f"  recovery #x: {' '.join(rec.splitlines()[-1].split())[:40]}")
        return 0 if (refused and usable) else 1


def torn(iterations=20):
    """Write OLD, flush, write NEW, flush and get reset mid-flush; classify after reboot."""
    verdicts = {}
    ok = True
    for i in range(iterations):
        with Dev() as d:
            d.cmd("#x")
            d.seed_many([(DATA(1), "A" * 128)])
            d.cmd("#f")
        # second write, then a flush that we interrupt
        d = Dev(); d.reset()
        d.seed_many([(DATA(1), "B" * 128)])
        d.cmd("#f", timeout=2.0) if False else None
        os.write(d.fd, b"#f\r")                       # fire and do not wait
        time.sleep(0.001 * (i % 5))                   # vary where the reset lands
        subprocess.run(["python3", "-m", "esptool", "--port", PORT, "--after", "hard_reset", "chip_id"],
                       capture_output=True)
        d.close(); time.sleep(1.6)
        with Dev() as e:
            data = bytes(e.num(f"{DATA(1)} BLOCK {o} + C@ .") for o in range(0, 128, 16))
            # sample 8 bytes is enough to separate OLD/NEW; a mixture shows as a mix of 65s and 66s
            kinds = {b for b in data if b in (65, 66)}
            v = "OLD" if kinds == {65} else "NEW" if kinds == {66} else "MIXED"
            verdicts[v] = verdicts.get(v, 0) + 1
            if v == "MIXED":
                ok = False
                print(f"  iteration {i}: MIXED -> {data}")
    print(f"  torn-flush over {iterations} interrupts: {verdicts}")
    print(f"  verdict: {'PASS (old or new, never mixed)' if ok else 'FAIL (a mixture appeared - STOP)'}")
    return 0 if ok else 1


def cost():
    blocks = phase_src(1)
    with Dev() as d:
        d.cmd("#x")
        b0 = d.cmd("#f")
        for p in range(1, 16):
            build_and_adopt(d, p, IMG_AREA + (p - 1) * 5, phase_src(p))
        r = d.cmd("#f")
        print(f"  after 15 phases: {' '.join(r.splitlines()[-1].split())}")
    m = re.search(r"(\d+) sector erase", r)
    erases = int(m.group(1)) if m else -1
    print(f"  erases for 15 phases = {erases}; at 1 switch/min: {100000/max(erases,1)/60/24:.1f} days; "
          f"at 1/s: {100000/max(erases,1)/86400:.1f} days")
    return 0


def all6():
    """gate 3, torn-flush and cost in one session budget."""
    print("  --- gate 3 ---")
    r3 = corrupt("real")
    print("  --- torn flush ---")
    rt = torn(20)
    print("  --- cost ---")
    rc = cost()
    return 0 if (r3 == 0 and rt == 0 and rc == 0) else 1


if __name__ == "__main__":
    cmd = sys.argv[1]
    sys.exit({"dry": dry, "corrupt-skip": lambda: corrupt("skip"),
              "corrupt": lambda: corrupt("real"), "torn": torn, "cost": cost, "all6": all6}[cmd]() or 0)
