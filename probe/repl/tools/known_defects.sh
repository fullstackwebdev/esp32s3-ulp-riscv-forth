#!/usr/bin/env bash
# tools/known_defects.sh — run the probes that pin OPEN DEFECTS, and report them.
#
# GUARDRAIL: probes here live OUTSIDE tests/*.fs (fixtures/ is fine), which requires a golden per file: a known-defect probe in
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
# ---- F-BLK-TAIL: a block longer than one tib pass loses its tail --------------------------------------------
# GUARDRAIL: expected output states the CORRECT behaviour (42), not the current behaviour. The closing ';' of the
# definition in this probe sits at offset 96, past the chip's 96-byte tib pass, so the block is delivered in two
# chunks and the tail can arrive after the next line has started - measured on the trace as the following line being
# read at STATE=1 with the stray ';' arriving afterwards.
run_block() {
    local name=$1 file=$2 want=$3 got
    local bin=artifacts/host_blk
    [ -x "$bin" ] || { echo "known_defects: $bin missing — run tests/run.sh first"; exit 2; }
    got=$("$bin" -k "$PRELUDE" src/p39b_overlay.fs "$file" 2>/dev/null | grep -av '^SRV ' | ./artifacts/expand | tr -d '\n')
    if [ "$got" = "$want" ]; then
        echo "FIXED   $name (got '$got') — remove the probe and add a real test"
    else
        echo "DEFECT  $name: want '$want', got '$got'"
    fi
}
run_block F-BLK-TAIL tests/fixtures/known_defect_tail.fs 42
