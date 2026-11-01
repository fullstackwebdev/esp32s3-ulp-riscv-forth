#!/usr/bin/env python3
"""golden_battery.py — a fixed behavioural battery with outputs recorded from a known-good build.

The asm dispatcher has NO host twin (the host suite runs the C engine), so the only way to prove a rewrite
is behaviour-preserving is to replay a recorded battery on the device and compare byte-for-byte.

    record  : run the battery on the current build and write tests/golden/device_battery.json
    check   : run it again and diff against the golden file (exit 1 on any difference)

GUARDRAIL: record OUTPUTS, never addresses or timings. `' W .`, `HERE`, `LATEST` and every xt MOVE when the image
changes size - a battery that stored them would fail the rewrite for the right reason and tell us nothing. Only values
that must not change are recorded; sizes are reported separately as informational.
"""
import sys, json, re, os, time, select, pathlib

sys.path.insert(0, "tools"); sys.path.insert(0, "tests")
from devio import Dev
from step4 import build_and_adopt, phase_src, IMG_AREA

GOLDEN = pathlib.Path("tests/golden/device_battery.json")

# (name, [lines]) - each line must fit the 63-byte interactive ring
LINES = [
    ("arith",       ["2 3 + ."]),
    ("arith-nest",  ["1 2 3 + * ."]),
    ("divmod",      ["7 2 /MOD . 32 EMIT ."]),
    ("stack-ops",   ["1 2 DUP . 32 EMIT SWAP . 32 EMIT ."]),
    ("compare",     ["3 4 < . 32 EMIT 4 3 < . 32 EMIT 4 4 = . 32 EMIT 0 0= ."]),
    ("cell",        ["CREATE v 0 ,", "42 v ! v @ ."]),
    # Documents the layer's real semantics: BLOCK ALWAYS re-fetches, and the dirty check only refuses a DIFFERENT block.
    # So a same-block re-read without SAVE silently returns the stored bytes (measured: wrote 200, read 32 = the blank
    # fill). Recorded deliberately as gold, so a future change that alters it is visible.
    # GUARDRAIL: seed the block to a known fill FIRST. Recorded on a store where block 0 happened to be space-filled, the
    # entry then read 255 on a freshly erased store and the battery reported a false regression - the gold was testing
    # store history, not the engine. A battery entry must bring its own state.
    ("block-refetch", ["#seed0", "0 BLOCK 0 + 200 SWAP C! UPDATE 0 BLOCK 0 + C@ ."]),
    ("colon-def",   [": SQ DUP * ;", "9 SQ ."]),
    ("begin-until", [": CD 0 BEGIN 1 + DUP 5 = UNTIL ;", "CD ."]),
    ("begin-while", [": CW 0 BEGIN DUP 5 < WHILE 1 + REPEAT ;", "CW ."]),
    ("underflow",   ["DROP", "2 3 + ."]),
    # GUARDRAIL: every line must fit the 63-byte ring; a 69-char version was refused whole.
    ("block-rw",    ["0 BLOCK 0 + 65 SWAP C! UPDATE SAVE DROP",
                     "0 BLOCK 0 + C@ ."]),
    # GUARDRAIL: end with a SAVE on the SAME block. A refused `1 BLOCK` leaves the layer dirty for block 0, and every
    # later `BLOCK` of a different block is then refused BK_DIRTY - which silently poisons the image cycle below.
    ("block-write2", ["0 BLOCK 2 + 67 SWAP C! UPDATE SAVE DROP"]),
    # EXCLUDED: a 60-char line of `DUP ` repeats arrives at the HP as 55 bytes + a 5-byte `DROP` line ("line too long:
    # 5 bytes"), i.e. something splits it mid-line. A 64-char line is refused as 64 (correct), so the split is specific to
    # this shape. Mid-line splitting is the class that once corrupted long definitions silently, so it is recorded as an
    # OPEN QUESTION in docs/24-dispatch.md rather than frozen into gold.
    ("line-ok",     ["1 2 + ."]),
    # GUARDRAIL: every entry that RAISES AN ERROR goes last. An error rewinds the dictionary to the save point, and a
    # dump+adopt performed afterwards hangs the machine (measured: `W @ EXECUTE` silent for 15 s). That is a separate
    # defect - recorded in docs/24-dispatch.md - and the battery must not depend on it either way.
    # boundary: 64 chars is one over the ring (63 + CR) and must be refused WHOLE; nothing in it may execute
    ("line-long",   ["DUP " * 16]),
    ("undefined",   ["NOPE"]),
]

ECHO = re.compile(r"^(#|NOPE|1 2|\:|CREATE|0 BLOCK)")

# GUARDRAIL: attribute output per ENTRY with a sentinel, never by "read until ok". A leftover `ok` from the previous line
# satisfied the marker and the battery recorded `3 ok` for a line that was REFUSED as too long - the same echo-pollution
# class that has bitten this project before. The sentinel is `<900+i> .`, which no entry prints.
def read_until(d, token, timeout=8.0):
    buf, end = b"", time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([d.fd], [], [], 0.02)
        if r:
            buf += os.read(d.fd, 4096)
            if token.encode() in buf:
                return buf.decode(errors="replace")
    return buf.decode(errors="replace")


def entry(d, i, lines):
    d.drain(0.05, 2.0)                      # GUARDRAIL: drain FIRST. Without it an entry's transcript starts with the
                                            # previous entry's tail, which recorded a refused line as "line too long: 5 bytes".
    sent = 900 + i
    for line in lines:
        os.write(d.fd, line.encode() + b"\r")
    os.write(d.fd, f"{sent} .".encode() + b"\r")
    raw = read_until(d, f"{sent} ok")
    out = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s or s in lines or s == "ok" or s == f"{sent} .":
            continue
        if s.startswith(f"{sent} ok"):
            s = s[len(f"{sent} ok"):].strip()
            if not s:
                continue
        out.append(s)
    return out


def normalise(reply, sent):
    """Keep only what the MACHINE said: drop the echoed command and trailing `ok`."""
    out = []
    for ln in reply.splitlines():
        s = ln.strip()
        if not s or s == sent.strip() or s == "ok":
            continue
        out.append(s)
    return out


def run(d):
    got = {}
    # GUARDRAIL: the image cycle runs FIRST, on a freshly booted dictionary. Running it after any error entry hangs.
    d.cmd("#x" if False else "0 DROP")
    d.cmd("0 BLOCK CONSTANT W")
    ok, cells, _ = build_and_adopt(d, 1, IMG_AREA, phase_src(1), execute=False)
    d.cmd("W @ EXECUTE", timeout=15.0)
    got["image-exec"] = [str(cells), str([d.num(f"z{i} @ .") for i in range(1, 7)])]
    # EXCLUDED (named reason, not skipped silently): a `9 LOAD` of `: T 7 . ;` answers `T?` here, immediately after an
    # image cycle, while step4 and capabilities load the same way and PASS. Until that disagreement is understood, neither
    # answer may be frozen into the golden file. Tracked in docs/24-dispatch.md as an open question.
    # d.seed_many([(9, ": T 7 . ;".ljust(128))])
    # got["load"] = entry(d, 50, ["9 LOAD", "T ."])
    for i, (name, lines) in enumerate(LINES):
        if lines and lines[0] == "#seed0":
            d.seed_many([(0, " " * 128)])
            lines = lines[1:]
        got[name] = entry(d, i, lines)
    # a block LOAD, seeded through the HP path, run BEFORE the error entries: after a rewind it answers `T?`
    return got


def main(mode):
    with Dev() as d:
        got = run(d)
        info = d.cmd("#i", timeout=8.0)
    sizes = [l.strip() for l in info.splitlines() if "store ok" in l]
    if mode == "record":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
        print(f"  recorded {len(got)} entries -> {GOLDEN}")
        if sizes:
            print(f"  informational (NOT compared): {sizes[0][:80]}")
        return 0
    want = json.loads(GOLDEN.read_text())
    bad = [k for k in want if got.get(k) != want[k]]
    for k in bad:
        print(f"  DIFF {k}:")
        print(f"    was  {want[k]}")
        print(f"    now  {got.get(k)}")
    print(f"  battery: {len(want) - len(bad)}/{len(want)} identical")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
