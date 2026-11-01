#!/usr/bin/env python3
"""lint_vocab.py — the linter's word table, checked against the machine.

Why this file exists: `PRIMS` in tools/lint_forth.py said `MOD` was a word. It was not. The linter therefore reported a
launcher containing `100 MOD` as CLEAN, and the chip answered `MOD?` while compiling block 79 — two devices away from
the line that was wrong. A linter that certifies a word the machine does not have is worse than no linter, because it
is believed.

The machine already answers this: `' NAME .` gives an xt, or `NAME?` for a word it does not have (devio.preflight is
built on the same fact). So the table is no longer self-certifying.

Direction checked: every name the linter claims, asked of the device. Control-flow words and `."` are not dictionary
entries and are skipped by name.

GUARDRAIL: run this against a FRESH machine — the launcher defines extra words, and a resident `.N` would make this test
pass for a linter whose table is still wrong. cli.connect() asserts freshness for exactly this reason.
"""
import os, sys, pathlib

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "probe" / "repl" / "tools"))

PORT = os.environ.get("PORT_DEV", "/dev/ttyACM1")
# GUARDRAIL: these are COMPILER WORDS and string literals, not dictionary entries - `' IF .` answers IF? on a machine
# where IF works perfectly. Asking about them would fail this test for no reason.
NOT_A_WORD = {"IF", "ELSE", "THEN", "BEGIN", "UNTIL", "WHILE", "REPEAT", "AGAIN", "DO", "LOOP", "+LOOP", '."'}


def main():
    from lint_forth import PRIMS, CONTROL
    import cli
    dev = cli.connect(PORT, 1.0)
    if not dev:
        return 2
    missing = []
    try:
        names = sorted(set(PRIMS) - NOT_A_WORD - CONTROL)
        for name in names:
            try:
                rep = dev.cmd(f"' {name} .", timeout=4.0, allow_error=True)
            except Exception as e:
                missing.append((name, f"no answer ({type(e).__name__})"))
                continue
            body = rep.replace(f"' {name} .", "").strip()
            # `52 ok` is an xt; `NAME?` (or a bare `?`) means the machine does not know the word
            if "?" in body or not any(ch.isdigit() for ch in body):
                missing.append((name, body.replace("\n", " ")[:40]))
        print(f"  checked {len(names)} names from the linter's PRIMS against the device")
        for name, why in missing:
            print(f"  FAIL  the linter claims `{name}`, the machine says: {why}")
        print(f"\n  {len(names) - len(missing)}/{len(names)} names exist on the machine")
        return 1 if missing else 0
    finally:
        dev.close()


if __name__ == "__main__":
    sys.exit(main())
