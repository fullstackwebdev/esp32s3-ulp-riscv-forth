#!/usr/bin/env bash
# sweep.sh — one row per compiler lever, on top of a chosen engine shape.
#   ./sweep.sh <shape-name> [shape flags ...]
# GUARDRAIL: every row is built by measure.sh from the same command IDF recorded, so a lever that the
# ULP toolchain silently ignores shows up as an identical sha256 in two rows — which is the signal to
# distrust the row, not to believe the zero.
set -uo pipefail
cd "$(dirname "$0")"
SHAPE=$1; shift || true
OUTF=out/sweep-$SHAPE.txt
: > "$OUTF"
run() { local n=$1; shift
  timeout 600 nice -n 15 ./measure.sh "$n" "$@" 2>&1 | grep -v "^ *-I" | tail -2 | tee -a "$OUTF"
}
run "${SHAPE}_ref"  "$@"
run "${SHAPE}_mrelax"   "$@" -mrelax
LINK_EXTRA=-mrelax run "${SHAPE}_mrelax_link" "$@" -mrelax
run "${SHAPE}_nojumptab" "$@" -fno-jump-tables
run "${SHAPE}_swconv"    "$@" -ftree-switch-conversion
run "${SHAPE}_noswconv"  "$@" -fno-tree-switch-conversion
run "${SHAPE}_medany"    "$@" -mcmodel=medany
run "${SHAPE}_medlow"    "$@" -mcmodel=medlow
run "${SHAPE}_fira_all"  "$@" -fira-region=all
run "${SHAPE}_align1"    "$@" -falign-functions=1
run "${SHAPE}_omitfp"    "$@" -fomit-frame-pointer
run "${SHAPE}_no_omitfp" "$@" -fno-omit-frame-pointer
run "${SHAPE}_Oz"        "$@" -Oz
run "${SHAPE}_nosave_restore" "$@" -mno-save-restore
run "${SHAPE}_nocrossjump"    "$@" -fno-crossjumping
run "${SHAPE}_align2"    "$@" -falign-functions=2 -falign-jumps=2 -falign-loops=2
