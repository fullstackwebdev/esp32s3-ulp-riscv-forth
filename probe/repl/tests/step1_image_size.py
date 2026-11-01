#!/usr/bin/env python3
"""step1_size.py — STEP 1 gate: how many BLOCKS does an image of the phase need?

No dumper is needed for the gate: the prelude's SEAL captures the sealed pointers in `bh`/`bl`, so the phase's own
code and header extents are two subtractions. Measured on the chip, per phase slot.

GUARDRAIL: the dumper cannot live in the overlay WITH the phase. A Forth dumper is ~370 B compiled, the phase is 516 B,
and the window is ~704 B on the host / ~690 B on the chip - measured as ERR_DICT on the host run that tried it. So the
image WRITER (step 3) has to be resident (costs application bytes: ask first) or run as a phase of its own.
"""
import sys, math, re, pathlib
sys.path.insert(0, "tools")
from devio import Dev
from fsplit import split_defs

SLASH = re.compile(r"\\.*")
PAREN = re.compile(r"\([^)]*\)")

src = pathlib.Path("tests/ph1.fsx").read_text()
src = " ".join(PAREN.sub("", SLASH.sub("", src)).split())
blocks = split_defs(src, 128)
PATTERN = ("0123456789" * 13)[:128]

print(f"source: {len(blocks)} blocks, {sum(len(b) for b in blocks)} B")
gate_blocks = math.floor(0.65 * len(blocks))
print(f"gate: image must need <= {gate_blocks} blocks ({65}% of {len(blocks)})")

worst = 0
for p in (1, 8, 15):
    base = 8 + (p - 1) * len(blocks)
    with Dev() as d:
        d.seed_many([(2, " " * 128), (4, PATTERN)] + [(base + k, b) for k, b in enumerate(blocks)])
        d.cmd("SEAL")
        d.cmd("2 OVL")
        for k in range(len(blocks)):
            d.cmd(f"{base + k} LOAD", timeout=10.0)
        code = d.num("HERE bh @ - .")
        hdr = d.num("bl @ LATEST - .")
    # GUARDRAIL: the descriptor does not need its own block - it shares the stream (12 B against a 128 B block). Counting
    # it as a separate block overstated the image by one block, and one block is exactly the difference between the gate
    # passing and failing at this phase size. Report BOTH packings; the loader is free to align the image at a block
    # boundary, which is the assumption behind "packed".
    desc = 12
    need_naive = 1 + math.ceil((code + hdr) / 128)
    need = math.ceil((desc + code + hdr) / 128)
    worst = max(worst, need)
    print(f"  phase {p:2d}: code {code:4d} B  headers {hdr:3d} B ({hdr // 3} words)  "
          f"=> packed {need} blocks ({need / len(blocks) * 100:.0f}%), descriptor-own-block {need_naive} "
          f"({need_naive / len(blocks) * 100:.0f}%)")

print(f"GATE: {'PASS' if worst <= gate_blocks else 'FAIL'} (worst {worst} vs allowed {gate_blocks})")
