#!/usr/bin/env python3
"""lintgate.py - the one place that decides whether a Forth source may run.

    python3 lintgate.py --repl  file.fs [file.fs ...]      # typed at the prompt
    python3 lintgate.py --phase file.fs [file.fs ...]      # block-uploaded phase

Exit 0 = clean, 1 = findings (printed), 2 = the linter itself failed.

WHY THIS EXISTS: `tools/lint_forth.py` is the only thing that knows what this machine refuses silently - a line over the
63 B input ring, a definition that cannot fit one interpret-state boundary, a control structure split across typed
lines, an odd `C,` count that leaves HERE odd, a `\` comment inside a block source. Those failures have no message on
the device; the word simply is not there, and the symptom appears later as `NAME?` or as a receiver that hears nothing.
So the linter is a BUILD GATE, not advice: every loader in tests/ and every generate-then-load script runs through
here, and a finding stops the run before the board is touched.

r AGENTS.md carries the rule in one line: all Forth code goes through the linter.
"""
import argparse
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def lint(paths, mode, use=()):
    """Run the linter and return the findings as a list of lines (empty = clean).

    GUARDRAIL: `use` names files that are ALREADY loaded when this one runs, so their words are in scope. Without it,
    a dependent source (the receive words need the driver's NSSLO) is refused for a use-before-definition that never
    happens on the machine - and a gate that cries wolf on working code gets switched off.
    """
    ctx = []
    for u in use:
        ctx += ["--use", str(u)]
    cmd = [sys.executable, str(HERE / "lint_forth.py"), mode, *ctx, *map(str, paths)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode not in (0, 1):
        raise RuntimeError(f"lintgate: the linter failed to run: {r.stderr.strip()[-300:]}")
    findings = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith(str(paths[0]).split("/")[0]) or
                (": R" in l and l.strip())]
    return [l for l in findings if ": R" in l]


def require_clean(paths, mode="--repl", where="", use=()):
    """Refuse to continue unless every file is clean. Raises SystemExit with the findings attached."""
    bad = lint(paths, mode, use)
    if bad:
        raise SystemExit(f"lintgate{' (' + where + ')' if where else ''}: {len(bad)} finding(s) - fix these before "
                         f"the board sees the file:\n  " + "\n  ".join(bad[:12]))
    return True


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] not in ("--repl", "--phase") or len(argv) < 2:
        print("usage: lintgate.py {--repl|--phase} [--after prior.fs] file.fs [file.fs ...]", file=sys.stderr)
        return 2
    mode, files, use = argv[0], [], []
    i = 1
    while i < len(argv):
        if argv[i] == "--after":
            use.append(argv[i + 1]); i += 2
        else:
            files.append(argv[i]); i += 1
    bad = lint(files, mode, use)
    if bad:
        print(f"lintgate: {len(bad)} finding(s)")
        for l in bad:
            print("  " + l)
        return 1
    print(f"lintgate: clean ({mode}) - {len(files)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
