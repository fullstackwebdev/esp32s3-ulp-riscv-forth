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
   13  bad_r16.fs      a PHASE that CREATEs its own storage           R16 phase state
   14  bad_r18.fs      a PHASE that names no return path              R18 no return

GUARDRAIL: R16/R18 are PHASE rules and are applied ONLY to the entries marked `phase` below - a phase is replaced
on every adopt (docs/26), so owning storage or naming no return path is a bug there and correct elsewhere. 05_cells.fs
CREATEs a cell and every REPL demo returns to the prompt; a default-on rule would flag both and be turned off.
`--phase` runs just those entries, which is the fast check while editing the phase rules.

**Run this after every change to the linter** — that is what makes it a test of the linter and not just a test of the
machine. A rule that starts firing on a GOOD program is a false positive; a rule that stops firing on a BAD one is a
false negative; both show up here as PASS/FAIL, with the rule named.

    python3 tools/sink.py                lint only (no board, ~50 ms) - the default gate
    python3 tools/sink.py --phase        only the PHASE entries (R16/R18), ~10 ms, while editing those rules
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

# (file, claim, expected lint rule or None for clean, expected device output or None to skip the board, mode)
# GUARDRAIL: the 5th field is `phase` for the two entries that are linted as PHASE sources (R16/R18). It is explicit
# per entry, not a global switch: the corpus is one list, and "which rules apply" must be readable from the entry that
# wants them, or a good program starts failing the day the switch flips.
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
    # GUARDRAIL: `'` must be exercised by a program that RUNS, not only by a lint fixture. The tick pushes an xt and
    # SKIPS its operand - the shape that made an undefined ticked word invisible to the walk - and the dispatcher
    # depends on it, so the corpus proves the chip executes `' BUMP EXECUTE` twice (counter 2) as well as the linter
    # rejecting a tick of a word that does not exist.
    ("06_tick.fs",   "`\'` pushes an xt and EXECUTE runs it",      None,            "2"),
    ("bad_tick.fs",  "a `\'` of a word that does not exist",       "R2 order",      None),
    # GUARDRAIL: the launcher's failed-adopt arm carried this exact bug for a whole turn: `' NOOP` inside a definition
    # compiles a RUN-time parse, so the safety path parsed input instead of running NOOP, and nothing caught it. The
    # corpus now holds both directions: `[']` is the good form (06_tick above) and a bare `'` in a body is R12.
    ("bad_r12.fs",   "a bare tick inside a definition",          "R12 tick",      None),
    # The App Store contract (docs/26): a phase is REPLACED on every adopt and must name its way back to the shelf.
    # Both files here FAIL device use by construction - the first would lose its cell on the next adopt, the second
    # can only be left by a reset - so they are lint-only, like the rest of the bad_* entries.
    ("bad_r16.fs",   "a PHASE that CREATEs its own storage",      "R16 phase state", None, "phase"),
    ("bad_r18.fs",   "a PHASE that names no return path",         "R18 no return",   None, "phase"),
]

# 04_escape.fs emits escape bytes, so its device check is a byte pattern rather than text.
PY_CHECKS = {"PY:04": lambda out: b"\x1b[2J" in out and b"\x1b[31m" in out and b"ok" in out and b"\x00" in out}


def lint(src, phase=False):
    import lint_forth
    rules = lint_forth.lint_definitions(src) + lint_forth.check_blocks(src)
    if phase:
        rules += lint_forth.lint_phase(src)
    return [r for _, r, _ in rules]


def run_lint(only=None, phase_only=False):
    print("  sink: linting the corpus (this is also the linter's regression suite)"
          + (" - PHASE entries only" if phase_only else ""))
    bad = 0
    for entry in CORPUS:
        f, claim, want, _dev = entry[:4]
        if only and f != only:
            continue
        if phase_only and (len(entry) < 5 or entry[4] != "phase"):
            continue
        got = lint((SINK / f).read_text(), phase=len(entry) > 4 and entry[4] == "phase")
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
        for entry in CORPUS:
            f, claim, _want, expect = entry[:4]
            # GUARDRAIL: a PHASE entry has no RUNSINK on purpose (a phase is entered by the dispatcher, not called
            # from the REPL), so the board half must skip it for the same reason it skips a lint-only entry.
            if len(entry) > 4 and entry[4] == "phase":
                continue
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
    phase_only = "--phase" in argv
    bad = run_lint(only, phase_only)
    if "--device" in argv:
        bad += run_device(only)
    print(f"\n  sink: {'all entries pass' if not bad else f'{bad} FAILING entry/entries'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
