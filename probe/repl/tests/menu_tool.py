#!/usr/bin/env python3
"""menu_tool.py — STEP 2: a menu phase hands a value to a tool phase through the STORE.

The point is not the program, it is the question the gate asks: what must a tool reach that it cannot? Here the handoff
is a byte in block 5, so the resident set gains nothing. Whatever the tool still needed is the finding to record.

Design (and why it is shaped this way):
  MENU  phase: reads a choice (fixed here), writes it to block 5, SAVEs, prints 'M'.
  TOOL  phase: reads block 5, computes choice*3, prints 'T' and the result.
  The switch between them is `2 OVL` (rewind to the sealed state) then loading the other phase - i.e. exactly what a
  resident loop does, with no handler calling another phase.

GUARDRAIL: the two phases must be seeded into DIFFERENT block ranges and neither may overlap the data block (5) or the
rewind target (2). Sharing a range silently overwrites one phase's source with the other's and the failure looks like a
missing word.

Usage: menu_tool.py [--device]
"""
import argparse, pathlib, re, subprocess, sys
sys.path.insert(0, "tools")
from devio import Dev
from fsplit import split_defs

# GUARDRAIL: DATA_BLK must be a block that ANSWERS. Block 5 is the host fake server's deliberately silent block (the
# no-answer path that tests/blocks_noserver.fs depends on) and block 7 answers with a bad checksum. Using 5 measured as
# ERR_NO_SERVER, then a LATCHED ERR_BUSY that made every later block call fail - the phase looked broken, the block was.
MENU_BLK, TOOL_BLK, DATA_BLK = 8, 12, 6
MENU_SRC = ": MENU 7 6 BLOCK C! UPDATE SAVE DROP 77 EMIT ;"
TOOL_SRC = ": TOOL 6 BLOCK C@ 3 * 84 EMIT . ;"


def blocks_of(text):
    return split_defs(" ".join(text.split()), 128)


def seed_file(path, items):
    path.write_text("".join(f"{b} {t.encode().hex()}\n" for b, t in items))


def host():
    work = pathlib.Path(".auto/tmp/menu_tool.blocks")
    seed_file(work, [(2, " " * 128), (DATA_BLK, " " * 128)]
              + [(MENU_BLK + k, b) for k, b in enumerate(blocks_of(MENU_SRC))]
              + [(TOOL_BLK + k, b) for k, b in enumerate(blocks_of(TOOL_SRC))])
    drive = pathlib.Path(".auto/tmp/menu_tool.fs")
    drive.write_text("SEAL\n2 OVL\n"
                     f"{MENU_BLK} LOAD\nMENU\n"          # menu writes the store, prints M
                     "2 OVL\n"                          # rewind: the menu phase is gone
                     f"{TOOL_BLK} LOAD\nTOOL\n"          # tool reads the store, prints T and the value
                     f"{DATA_BLK} BLOCK C@ . 32 EMIT\n")
    out = subprocess.run(["artifacts/host_blk", "-B", str(work), "-k", "src/p39_prelude.fs",
                          "src/p39b_overlay.fs", str(drive)], capture_output=True)
    return out.stdout.decode("latin-1").split("SRV")[0]


def device():
    with Dev() as d:
        items = [(2, " " * 128), (DATA_BLK, " " * 128)]
        items += [(MENU_BLK + k, b) for k, b in enumerate(blocks_of(MENU_SRC))]
        items += [(TOOL_BLK + k, b) for k, b in enumerate(blocks_of(TOOL_SRC))]
        missing = d.seed_many(items)
        if missing:
            return f"seed failed for {missing}"
        d.cmd("SEAL")
        d.cmd("2 OVL")
        d.cmd(f"{MENU_BLK} LOAD")
        m = d.cmd("MENU", timeout=10.0)
        d.cmd("2 OVL")
        d.cmd(f"{TOOL_BLK} LOAD")
        t = d.cmd("TOOL", timeout=10.0)
        stored = d.num(f"{DATA_BLK} BLOCK C@ .")
        return f"MENU->{m.strip()[-6:]!r} TOOL->{t.strip()[-8:]!r} store={stored}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", action="store_true")
    a = ap.parse_args()
    print("  menu blocks:", blocks_of(MENU_SRC), "tool blocks:", blocks_of(TOOL_SRC))
    if a.device:
        print("  device:", device())
    else:
        print("  host:", " | ".join(x.strip() for x in host().split("\n") if x.strip())[-160:])
    return 0


sys.exit(main())
