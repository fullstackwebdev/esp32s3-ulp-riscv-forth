#!/usr/bin/env python3
"""sink.py — the "kitchen sink" corpus: small Forth programs that pin what this machine DOES, and that double as the
linter's regression suite.

Two jobs in one corpus, in the order the claims matter:

    #  file           establishes                                    lint      device output
    1  01_arith.fs     arithmetic and the stack                        clean     6 6 20
    2  02_loops.fs     BEGIN/WHILE/REPEAT with a CREATE'd cell         clean     15 43
    3  03_digits.fs    two-digit printing with a BOUNDED EMIT (R7)     clean     0 1 2 … 12
    4  04_escape.fs    the ANSI byte path and the frame sentinel       clean     ESC[2J ESC[31m ok NUL
    5  05_cells.fs     CREATE/`!`/`@` — data below the seal            clean     3 8
    6  bad_r01.fs      a `\\` comment compiles as words                R1 comment   (lint only)
    7  bad_r02.fs      a word used before it exists                    R2 order     (lint only)
    8  bad_r03.fs      a body that pops more than it holds             R3 underflow
    9  bad_r04.fs      a body that leaves items nobody wants           R4 leak
   10  bad_r07.fs      an EMIT that is not provably 0..127 (R7)        R7 byte range  (must FAIL device)
   11  bad_r08.fs      KEY never tested against -1                    R8 key -1
   12  bad_r11.fs      a definition that cannot fit one block          R11 fit      (lint only)

**Run this after every change to the linter** — that is what makes it a test of the linter and not just a test of the
machine. A rule that starts firing on a GOOD program is a false positive; a rule that stops firing on a BAD one is a
false negative; both show up here as PASS/FAIL, with the rule named.

    python3 tools/sink.py                lint only (no board, ~50 ms) - the default gate
    python3 tools/sink.py --device       also upload and run the five good programs on the chip
    python3 tools/sink.py --device --only 03_digits.fs

GUARDRAIL: the good programs are SELF-CONTAINED and comment-free. `cli.upload()` sends the file text to the chip
verbatim (`fsplit` does not strip comments), and a sink program is uploaded onto a FRESH dictionary with no launcher, so
it cannot call resident words like `.N` — 03_digits.fs therefore defines its own, which is the same shape the launcher
uses and is the point of the entry.
GUARDRAIL: every file here is also part of the linter's INPUT. `bad_r01.fs` must keep its `\\` comment, and every "good"
file must stay lint-clean *by the rules*, not by exemption — a corpus that needs exemptions tests nothing.
"""
import sys, pathlib, subprocess

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[1]                  # probe/repl
SINK = HERE.parent.parent / "tests" / "sink"   # tools/ -> probe/repl/tests/sink
sys.path.insert(0, str(HERE.parent))    # tools/
sys.path.insert(0, str(ROOT.parent.parent))   # repo root, for cli.py in --device mode

# (file, claim, expected lint rule or None for clean, expected device output or None to skip the board)
CORPUS = [
    ("01_arith.fs",  "arithmetic and the stack",                 None,            "6620"),
    ("02_loops.fs",  "BEGIN/WHILE/REPEAT over a CREATE'd cell",  None,            "1543"),
    ("03_digits.fs", "two-digit printing with a bounded EMIT",   None,            "0 1 2 3 4 5 6 7 8 9 10 11 12 "),
    ("04_escape.fs", "the ANSI byte path and the sentinel",      None,            "PY:04"),
    ("05_cells.fs",  "CREATE / ! / @ below the seal",            None,            "38"),
    ("bad_r01.fs",   "a `\\` comment compiles as words",         "R1 comment",    None),
    ("bad_r02.fs",   "a word used before it exists",             "R2 order",      None),
    ("bad_r03.fs",   "a body that pops more than it holds",      "R3 underflow",  None),
    ("bad_r04.fs",   "a body that leaves items nobody wants",    "R4 leak",       None),
    ("bad_r07.fs",   "an EMIT that is not provably 0..127",      "R7 byte range", "MUST-FAIL"),
    ("bad_r08.fs",   "KEY never tested against -1",              "R8 key -1",     None),
    ("bad_r11.fs",   "a definition that cannot fit one block",   "R11 fit",       None),
]

# 04_escape.fs emits escape bytes, so its device check is a byte pattern rather than text.
PY_CHECKS = {"PY:04": lambda out: b"\x1b[2J" in out and b"\x1b[31m" in out and b"ok" in out and b"\x00" in out}


def lint(src):
    import lint_forth
    return [r for _, r, _ in (lint_forth.lint_definitions(src) + lint_forth.check_blocks(src))]


def run_lint(only=None):
    print("  sink: linting the corpus (this is also the linter's regression suite)")
    bad = 0
    for f, claim, want, _dev in CORPUS:
        if only and f != only:
            continue
        got = lint((SINK / f).read_text())
        ok = (not got) if want is None else (want in got)
        bad += 0 if ok else 1
        shown = ", ".join(sorted(set(got))) if got else "clean"
        print(f"  {'PASS' if ok else 'FAIL'}  {f:<14} {claim:<42} want {want or 'clean':<14} got {shown}")
    return bad


def run_device(only=None):
    """Upload each good program to a FRESH dictionary, call its RUNSINK, and check what came back.

    GUARDRAIL: every good file defines `: RUNSINK ( -- ) ... ;` and nothing at top level. `upload()` INTERPRETS as it
    compiles, so a top-level call would run inside the upload's own transcripts and the test could not say which bytes
    were the answer - measured while writing this runner.
    """
    import cli
    dev = cli.connect("/dev/ttyACM1", 1.0)
    if not dev:
        print("  sink: no board", file=sys.stderr)
        return 1
    bad = 0
    try:
        for f, claim, _want, expect in CORPUS:
            if only and f != only:
                continue
            if expect is None:
                continue                                  # lint-only entry
            if dev.num("HERE .") > 900:
                dev.reset(settle=0.3)
                # GUARDRAIL: the FIRST block op after a hard reset can answer ERR_BUSY - the store is still booting and
                # the layer is latched. Measured on the sink's first entry (HERE stayed 786, block 64 refused). One
                # abort plus one retry is the documented escape; without it the corpus fails for a reason that has
                # nothing to do with what it tests.
                dev.cmd("0 2 BLKXFER", timeout=6.0, allow_error=True)
            n, errs = cli.upload(dev, str(SINK / f), 64)
            if errs:
                dev.cmd("0 2 BLKXFER", timeout=6.0, allow_error=True)
                n, errs = cli.upload(dev, str(SINK / f), 64)
            if errs:
                print(f"  FAIL  {f:<14} {claim:<42} compile: {list(errs.values())[:1]}")
                bad += 1
                continue
            rep = dev.cmd("RUNSINK", timeout=8.0, allow_error=True)
            raw = rep.encode("latin-1")
            if expect == "MUST-FAIL":
                ok = b"ERR_" in raw                       # the machine proves the rule on itself
                shown = "; ".join(sorted({m for m in raw.decode("latin-1").split() if "ERR_" in m}))[:40]
            elif expect.startswith("PY:"):
                ok = PY_CHECKS[expect](raw)
                shown = f"{len(raw)} B"
            else:
                ok = expect.encode() in raw
                shown = repr(expect)
            bad += 0 if ok else 1
            print(f"  {'PASS' if ok else 'FAIL'}  {f:<14} {claim:<42} want {shown}")
    finally:
        dev.close()
    return bad


def main(argv):
    only = None
    if "--only" in argv:
        i = argv.index("--only")
        only = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    bad = run_lint(only)
    if "--device" in argv:
        bad += run_device(only)
    print(f"\n  sink: {'all entries pass' if not bad else f'{bad} FAILING entry/entries'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
