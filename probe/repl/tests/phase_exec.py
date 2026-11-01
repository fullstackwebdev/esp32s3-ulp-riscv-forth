#!/usr/bin/env python3
"""phase_exec.py — STEP 0 verifier: a phase must EXECUTE, not just compile.

Loads the phase source into a given block range and asserts the numbers its own `RUNPH1` prints match the HOST run of
the same bytes against the same data block. Size alone cannot tell a phase that ran from one that compiled to silence.

GUARDRAIL: the data block is seeded with the SAME printable pattern on both sides, and the expectation comes from the
host run rather than from a hand-computed constant - a hand-computed expectation tests my arithmetic, not the machine.

GUARDRAIL: every line sent is short. The console refuses lines over 63 bytes now (CMD_SIZE 64) instead of truncating
them, so a long drive line would fail loudly but look like a phase fault.

Usage: phase_exec.py [--phases 1,8,15] [--skip-block N]
"""
import argparse
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, "tools")
from devio import Dev
from fsplit import split_defs

DATA_BLK = 4
FIRST = 8                                  # block 0..7 belong to other tests
PATTERN = ("0123456789" * 13)[:128]


def phase_blocks():
    src = re.sub(r"\\.*", "", pathlib.Path("tests/ph1.fsx").read_text())
    src = " ".join(re.sub(r"\([^)]*\)", "", src).split())
    return split_defs(src, 128)


def host_expected(blocks, workdir):
    """The same bytes, the same data block, run by the host engine."""
    bfile = workdir / "phase_exec.blocks"
    bfile.write_text(
        "".join(f"{FIRST + k} {b.encode().hex()}\n" for k, b in enumerate(blocks))
        + f"2 {(' ' * 128).encode().hex()}\n"
        + f"{DATA_BLK} {PATTERN.encode().hex()}\n"
    )
    drive = workdir / "phase_exec_drive.fs"
    # GUARDRAIL: query each result cell EXPLICITLY instead of parsing what the phase prints. The phase's own SHOW
    # output runs together with the echo of `N LOAD`, whose block number is a digit string - the first attempt compared
    # `[8, 9, ..., 671235300005712838]` against the host's single concatenated number and reported three false FAILs.
    drive.write_text("SEAL\n2 OVL\n" + "".join(f"{FIRST + k} LOAD\n" for k in range(len(blocks)))
                     # GUARDRAIL: `.` emits no separator here, so six results run together into
                     # `671235300005712838` and cannot be split unambiguously. A space after each value makes the
                     # host stream parseable and keeps this comparison honest.
                     + "32 EMIT\n"          # GUARDRAIL: separator BEFORE the first query, or the phase's own last
                                             # number runs into it and six values parse as five plus one long blob.
                     + "".join(f"z{i} @ . 32 EMIT\n" for i in range(1, 7)))
    out = subprocess.run(["artifacts/host_blk", "-B", str(bfile), "-k", "src/p39_prelude.fs",
                          "src/p39b_overlay.fs", str(drive)],
                         capture_output=True, text=True).stdout.split("SRV")[0]
    # GUARDRAIL: the host engine does not echo source lines, so every number in stdout comes from the machine: the
    # phase's own SHOW (once or twice) and then MY six queries. Taking the last six is therefore exact; taking the last
    # number of each line lost five of them, because `.` emits no separator and they share one line.
    return Dev.nums(out)[-6:]


def device_run(phases, blocks, skip_block=None):
    results = {}
    with Dev() as d:
        for p in phases:
            base = FIRST + (p - 1) * len(blocks)
            if base + len(blocks) > 128:
                results[p] = ("NOT-RUN", f"needs blocks {base}..{base+len(blocks)-1}")
                continue
            d.reset()
            items = [(2, " " * 128), (DATA_BLK, PATTERN)]
            for k, b in enumerate(blocks):
                if skip_block is not None and base + k == skip_block:
                    continue                      # deliberate failure: leave this block unseeded
                items.append((base + k, b))
            missing = d.seed_many(items)
            d.cmd("SEAL")
            d.cmd("2 OVL")
            for k in range(len(blocks)):
                d.cmd(f"{base + k} LOAD", timeout=10.0)      # replies are echoes + phase output; not parsed
            # GUARDRAIL: a skipped block leaves the phase's cells undefined, so the query can error instead of
            # answering. That is a FAIL to report, not an exception to escape - the point of the deliberate-failure run
            # is to see this assertion fail.
            try:
                got = [d.num(f"z{i} @ .") for i in range(1, 7)]
            except Exception as exc:
                got = ["no-answer", str(exc)[:40]]
            results[p] = ("RAN", got)
            print(f"    phase {p:2d} (blocks {base}..{base+len(blocks)-1}): {got}")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phases", default="1,8,15")
    ap.add_argument("--skip-block", type=int, default=None)
    a = ap.parse_args()
    phases = [int(x) for x in a.phases.split(",")]
    blocks = phase_blocks()
    workdir = pathlib.Path(".auto/tmp")
    workdir.mkdir(parents=True, exist_ok=True)

    want = host_expected(blocks, workdir)
    print(f"host expectation ({len(blocks)} blocks, data block {DATA_BLK}): {want}")
    res = device_run(phases, blocks, a.skip_block)

    fail = 0
    for p in phases:
        state, got = res[p]
        if state != "RAN":
            print(f"  phase {p:2d}: NOT-RUN ({got})"); fail = 1; continue
        ok = got == want
        print(f"  phase {p:2d}: {'PASS' if ok else 'FAIL'}")
        fail |= 0 if ok else 1
    return fail


sys.exit(main())
