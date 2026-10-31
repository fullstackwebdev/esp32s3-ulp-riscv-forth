#!/usr/bin/env python3
"""fsplit.py — split Forth source into blocks at SAFE boundaries only.

GUARDRAIL: the default size is 92, NOT 128, because the CHIP's TIBSZ is 96. A block longer than one tib pass is
delivered in two: blk_refill cuts the first chunk back to a space, and the leftover (often the closing `;`) is
delivered on the SECOND refill - which only happens once the current line is dry. Measured on the host trace: block 9
ended `... NX REPEAT`, the driver's next line's `10` and `LOAD` were then read at ST=1 (so `10 LOAD` was COMPILED
instead of executed), and only after that did the stray `;` arrive. Keep every block under TIBSZ and the whole block
is one pass: no cut, no leftover, no ordering hazard.

GUARDRAIL: a block boundary is NOT a line boundary. Every token of a block is interpreted, the block ends, and the
NEXT thing interpreted is whatever the caller submits - which for a paged phase is `N LOAD`. If a `:` definition is
still open when the block ends, the machine is in COMPILE state, so that `N LOAD` is COMPILED into the open
definition instead of executed: the next block is never loaded, no error is raised, `LATEST` never moves, and the
phase silently assembles from its first block only. Measured on the chip as block 10 failing with `S2?` and blocks
11/12 raising ERR_STACK, and on the host as a trace whose last tokens are `10 LOAD 11 LOAD ...` all with ST=1 and a
refusal counter of zero.

GUARDRAIL: so a block may only be cut where the interpreter is in INTERPRET state - outside a `:` definition
(depth 0) and not immediately after a word that parses a name (`: CREATE CONSTANT VARIABLE '`). Cutting mid-`CREATE`
leaves CREATE asking the next block for a name it will never see.
GUARDRAIL: a single definition that cannot fit one block is a HARD FAILURE, not a silent split. The window is 128 B;
if the source needs more, the phase must be rewritten (or the window raised), and a machine that quietly cuts the
definition in half produces the exact silent corruption above.
"""
import sys


NAMEPARSERS = {":", "CREATE", "CONSTANT", "VARIABLE", "'"}


def safe_after(toks):
    """safe[j] is True when the machine is in INTERPRET state immediately after token j."""
    safe = []
    in_def = False
    expect_name = False
    for t in toks:
        if t in NAMEPARSERS and t != ":":
            expect_name = True
        elif t == ":":
            in_def = True
            expect_name = True
        elif t == ";":
            in_def = False
            expect_name = False
        else:
            expect_name = False
        safe.append(not in_def and not expect_name)
    return safe


def split_defs(text, size=92):
    """Greedy fill, then BACKTRACK to the last boundary where the machine is in interpret state."""
    toks = text.split()
    safe = safe_after(toks)
    blocks, i = [], 0
    while i < len(toks):
        end, length = i, 0
        while end < len(toks):
            add = len(toks[end]) + (1 if end > i else 0)
            if length + add > size:
                break
            length += add
            end += 1
        cut = None
        for j in range(end, i, -1):
            if safe[j - 1]:
                cut = j
                break
        if cut is None:
            raise SystemExit(
                f"REFUSING: no interpret-state boundary inside one {size} B block from token {i} "
                f"({toks[i]!r}); a single definition does not fit - rewrite the phase or raise the window")
        blocks.append(" ".join(toks[i:cut]))
        i = cut
    if blocks and not safe[-1]:
        raise SystemExit("REFUSING: source ends inside a definition (no closing ';')")
    return blocks


def selftest():
    """Checks that fail without the lessons: safe cuts only, and a hard refusal for an oversized definition."""
    ok = 0
    b = split_defs(": A 1 ; : B 2 ;", 12)
    assert all(not x.strip().startswith(";") for x in b), b
    assert " ".join(b) == ": A 1 ; : B 2 ;", b
    ok += 1
    try:
        split_defs(": LONG " + " ".join(["1"] * 40) + " ;", 20)
    except SystemExit:
        ok += 1
    else:
        raise SystemExit("FAIL: an oversized definition was split instead of refused")
    b = split_defs("4 CONSTANT C CREATE v 0 ,", 128)
    assert b == ["4 CONSTANT C CREATE v 0 ,"], b
    ok += 1
    print(f"fsplit selftest: {ok}/3 checks pass")


def main():
    if "--selftest" in sys.argv:
        selftest(); return
    if len(sys.argv) < 2:
        raise SystemExit("usage: fsplit.py <source.fs> [--out prefix] [--first-block N]")
    src = open(sys.argv[1]).read()
    import re
    src = re.sub(r"\\.*", "", src)                 # GUARDRAIL: `\` swallows the rest of a BLOCK - there is no line
    src = re.sub(r"\([^)]*\)", "", src)             # structure inside a block
    src = " ".join(src.split())
    blocks = split_defs(src)
    prefix, first = None, 8
    if "--out" in sys.argv:
        prefix = sys.argv[sys.argv.index("--out") + 1]
    if "--first-block" in sys.argv:
        first = int(sys.argv[sys.argv.index("--first-block") + 1])
    if prefix:
        for k, b in enumerate(blocks):
            open(f"{prefix}{k}.fsx", "w").write(b + "\n")
    print(f"{len(blocks)} block(s), {sum(len(b) for b in blocks)} B of source, block numbers {first}..{first+len(blocks)-1}")
    for k, b in enumerate(blocks):
        print(f"  {first+k}: {len(b):3d} B | {b[:70]}{'...' if len(b) > 70 else ''}")


if __name__ == "__main__":
    main()
