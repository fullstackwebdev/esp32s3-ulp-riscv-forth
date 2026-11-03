#!/usr/bin/env python3
"""Mutation-test the SX1262 table rules (R30-R33): re-introduce each bug we actually shipped and require the linter
to name it.

    python3 tests/lint_rules_selftest.py

A linter that never fires is indistinguishable from a linter that works, and every one of these mutants reached the
board this session. Each case mutates a copy of a known-good source, runs lintgate exactly as a loader would, and
requires the expected rule id in the output.
"""
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
SRC = REPO / "examples/apps/lora/loratx.fs"
WORK = REPO / "probe/results/lint_mutants"

CASES = [
    ("R30 spi opcode", "  5 C, 13 C, 7 C, 64 C, 43 C, 36 C,", "  2 C, 116 C, 43 C,"),
    ("R31 table count", "CFGPTR ! 18 ALL", "CFGPTR ! 15 ALL"),
    ("R32 frame length", "GO ( -- st ) 27 SETLEN TXBUF 27 CLKN", "GO ( -- st ) 26 SETLEN TXBUF 26 CLKN"),
    ("R33 tx clamp", "  4 C, 13 C, 8 C, 216 C, 94 C,\n  0 C,", ""),
]


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    src = SRC.read_text()
    fails = []
    for expect, old, new in CASES:
        if old not in src:
            print(f"  SKIP  {expect}: anchor not found in {SRC.name} (source changed?)")
            fails.append(expect)
            continue
        mutant = WORK / f"mutant_{expect.split()[0]}.fs"
        mutant.write_text(src.replace(old, new, 1))
        r = subprocess.run([sys.executable, str(HERE.parent / "tools/lintgate.py"), "--repl", str(mutant)],
                           capture_output=True, text=True)
        out = r.stdout + r.stderr
        ok = expect in out and r.returncode == 1
        print(f"  {'PASS' if ok else 'FAIL'}  {expect:18s} exit={r.returncode}")
        if not ok:
            fails.append(expect)
            for line in out.strip().splitlines()[:3]:
                print("        ", line)
    print(f"\n  {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
