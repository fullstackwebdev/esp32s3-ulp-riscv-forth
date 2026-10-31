#!/usr/bin/env bash
# tools/known_defects.sh — run the probes that pin OPEN DEFECTS, and report them.
#
# GUARDRAIL: these files live outside tests/*.fs on purpose. tests/run.sh globs that directory and requires a
# golden file per .fs, so a known-defect probe in there would either fail the suite forever or get its wrong
# output recorded — and "a green suite must never be achieved by recording a gap". Here the expected string is
# the CORRECT behaviour, so a fix turns the report to FIXED instead of a test quietly surviving.
set -uo pipefail
cd "$(dirname "$0")/.."
PRELUDE=src/p39_prelude.fs
BIN=artifacts/host_suite
[ -x "$BIN" ] || { echo "known_defects: $BIN missing — run tests/run.sh first"; exit 2; }

# name | file | expected-correct output
run() {
    local name=$1 file=$2 want=$3
    local got
    got=$("$BIN" "$PRELUDE" "$file" 2>/dev/null | tr -d '\n')
    if [ "$got" = "$want" ]; then
        echo "FIXED   $name (got '$got') — remove the probe and add a real test"
    else
        echo "DEFECT  $name: want '$want', got '$got'"
    fi
}

run "PAUSE interleaves two tasks" tests/known_defects/tasks_pause.fs "1324"
