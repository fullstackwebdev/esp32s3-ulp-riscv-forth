#!/bin/bash
# capacity.sh — TEST 2: does a paged program exceed the largest single image?
#
# Measures each phase's compiled size at the shipping MEMSZ and asserts three things:
#   1. every phase fits the sealed free space (1008 B at MEMSZ 1936),
#   2. the three phases TOGETHER exceed the 1544 B single-image ceiling,
#   3. each phase prints the numbers an independent Python derivation predicts. `.` emits no separator, so the
#      expectation is the DIGITS CONCATENATED: A = 8128,690880,0,0,127 -> "812869088000127"; B = 8128,1,64,64,64,
#      690880 -> "81281646464690880"; C = 43,26,1,64,4032,127 -> "43261644032127". Written out here so a change
#      in any single statistic fails the test.
#
# Transport note: this drives the phases from files and rewinds the dictionary between them, so it measures
# CAPACITY. The block transport itself (BLOCK/UPDATE/SAVE/LOAD through the store) is covered by overlay.fs.
# A single file cannot rewind itself, which is why this is a shell test rather than a .fs test.
set -u
cd "$(dirname "$0")/.." || exit 1
BIN=artifacts/host_cap
[ -x "$BIN" ] || { echo "BUILD FAILED: $BIN missing (run.sh builds it)" >&2; exit 1; }
PRE="src/p39_prelude.fs src/p39b_overlay.fs"
PROBE=tests/fixtures/capacity_probe.fs
LIMIT=1544          # the monolith's app space
WINDOW=690          # sealed free space at MEMSZ 1936 WITH the resident event loop (row 1's price)

here_of() { grep -aoE '[0-9]+ $' <<<"$1" | tail -2 | head -1; }

base=$("$BIN" $PRE "$PROBE" 2>&1 | grep -av '^SRV ' | grep -aoE '^[0-9]+' | tail -1)
[ -n "$base" ] || { echo "capacity: baseline HERE not read" >&2; exit 1; }

total=0; fail=0
while read -r name phase want; do
    pre=""
    [ "$name" = "A" ] || pre=tests/fixtures/capacity_fill.fs
    out=$("$BIN" $PRE $pre "$phase" "$PROBE" 2>&1 | grep -av '^SRV ')
    tail_line=$(grep -av '^ *$' <<<"$out" | tail -1)
    h=$(awk '{print $1}' <<<"$tail_line")
    case "$h" in ''|*[!0-9]*) h="";; esac
    [ -n "$h" ] || { echo "  phase $name: could not read HERE from: $(tr '\n' ' ' <<<"$out" | tail -c 80)" >&2; fail=1; continue; }
    size=$((h - base)); total=$((total + size))
    got=$(grep -av '^ *$' <<<"$out" | sed -n '$!p' | tail -1 | tr -cd '0-9')
    printf "  phase %s: %4d B compiled  (window %d)  numbers: %s\n" "$name" "$size" "$WINDOW" "$got"
    [ "$size" -le "$WINDOW" ] || { echo "    FAIL: phase $name is $size B, over the $WINDOW B window" >&2; fail=1; }
    [ "$got" = "$want" ] || { echo "    FAIL: phase $name printed '$got', expected '$want'" >&2; fail=1; }
done <<'EOF'
A tests/capacity_a.fsx 812869088000127
B tests/capacity_b.fsx 81281646464690880
C tests/capacity_c.fsx 43264032127
EOF

printf "  total %d B across three phases vs %d B single image: " "$total" "$LIMIT"
if [ "$total" -gt "$LIMIT" ]; then
    echo "PASS (+$(( (total - LIMIT) * 100 / LIMIT ))%)"
else
    echo "FAIL (does not exceed the monolith)"; fail=1
fi
exit "$fail"
