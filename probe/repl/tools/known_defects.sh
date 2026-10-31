#!/usr/bin/env bash
# tools/known_defects.sh — run the probes that pin OPEN DEFECTS, and report them.
#
# GUARDRAIL: probes here live OUTSIDE tests/*.fs, which requires a golden per file: a known-defect probe in
# there would either fail the suite forever or get its wrong output recorded — and "a green suite must never
# be achieved by recording a gap". Each entry states the CORRECT behaviour, so a fix reports FIXED (then the
# probe is promoted to a real test) instead of quietly surviving.
#
# Currently EMPTY: F-122 (PAUSE interleaving) was fixed and promoted to tests/tasks_pause.fs.
set -uo pipefail
cd "$(dirname "$0")/.."
PRELUDE=src/p39_prelude.fs
BIN=artifacts/host_suite
[ -x "$BIN" ] || { echo "known_defects: $BIN missing — run tests/run.sh first"; exit 2; }
run() {
    local name=$1 file=$2 want=$3 got
    got=$("$BIN" "$PRELUDE" "$file" 2>/dev/null | tr -d '\n')
    if [ "$got" = "$want" ]; then
        echo "FIXED   $name (got '$got') — remove the probe and add a real test"
    else
        echo "DEFECT  $name: want '$want', got '$got'"
    fi
}
echo "no open-defect probes"
