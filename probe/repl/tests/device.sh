#!/usr/bin/env bash
# device.sh — the HARDWARE tests, in one command, under the board lock.
#
# GUARDRAIL: these tests were each run by hand from a doc, which is how a shipped command (`./cli.py --library`) broke
# while every test stayed green: the tests carried their own copy of the build. A device test that nobody can run in
# one line is a test that gets run when someone remembers. This list is the whole memory.
#
# GUARDRAIL: the board lock is taken ONCE, here, for the whole run. Two of these scripts reset the chip; interleaving
# them produced "fresh boot" failures that were really two processes on one UART.
#
# GUARDRAIL: every test asserts its own fresh-boot precondition and exits non-zero on failure, so this runner must not
# swallow an exit code. `set -e` and no pipes around the commands: a green log from a red run is the failure mode this
# file exists to prevent.
set -euo pipefail
cd "$(dirname "$0")/.."
LOCK=../results/.board.lock
mkdir -p ../results
exec 9>"$LOCK"
flock -n 9 || { echo "board busy (another device run holds $LOCK)" >&2; exit 3; }

# GUARDRAIL: lint_vocab.py runs FIRST and against a fresh machine, because it asks `' WORD .` for every name the
# linter believes in, and ms_clock.py measures the ULP's only clock (MS).
# `linter believes in` -> `MOD` was in that table and not on the chip: the linter certified block 79 of a launcher that
# could not compile, and only the chip said so.
# GUARDRAIL: `tools/sink.py --device` is last and is the only runner that does not live in tests/: it is the
# CORPUS (small programs + their expected lint verdicts), so it doubles as the linter's regression suite.
# GUARDRAIL: dispatcher.py is the chain/window test - it builds 24 generated phases and requires the chain
# to reach the last one and return. It runs before programs.py because it resets to a bare dispatcher.
tests=(lint_vocab.py ms_clock.py dispatcher.py tui_menu.py adopt_sum.py programs.py tui_cli.py)
fail=0
for t in "${tests[@]}"; do
    echo
    echo "=== $t ==="
    if ! nice -n 10 python3 "tests/$t"; then
        fail=$((fail + 1))
        echo "=== $t FAILED ===" >&2
    fi
done

# GUARDRAIL: `tools/sink.py --device` lives in tools/ because it is the CORPUS - small programs plus the lint verdict
# each one must get - so it is the linter's regression suite as much as the machine's. It runs last because it is the
# only runner that resets the dictionary between every entry.
echo
echo "=== tools/sink.py --device (the corpus: 6 programs on the chip, 12 lint verdicts) ==="
if ! nice -n 10 python3 tools/sink.py --device; then
    fail=$((fail + 1))
    echo "=== sink.py FAILED ===" >&2
fi

echo
if [ "$fail" -ne 0 ]; then
    echo "device: $fail failure(s) across ${#tests[@]} test file(s) + the sink corpus" >&2
    exit 1
fi
echo "device: all ${#tests[@]} test files pass, plus the sink corpus"
