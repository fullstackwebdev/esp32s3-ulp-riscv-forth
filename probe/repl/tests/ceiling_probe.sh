#!/bin/bash
# ceiling_probe.sh — escalate until it breaks, report the HIGH SCORE, assert it beats the safe baseline.
#
# Start at SAFE phases (known to work), add one at a time, stop at the first N that fails; the last N that worked
# is the high score. This finds the limit instead of asserting a guess about it.
#
# GUARDRAIL: on the HOST the stop condition is the STORE, and the store cost is COMPUTED from comment-stripped
# source bytes, not probed - every phase is measured in a fresh process, so nothing accumulates and no N would ever
# fail on the host. The output names which bound stopped the run, so a computed ceiling is never read as a measured
# one. The measured version needs the chip (blocks are real there).
# GUARDRAIL: no destructive cleaning here. Each run gets a fresh timestamped directory under .auto/tmp, which is
# append-only by project rule; deleting an earlier probe's output would destroy evidence.
set -u
cd "$(dirname "$0")/.." || exit 1
BIN=artifacts/host_cap
PRE="src/p39_prelude.fs src/p39b_overlay.fs"
FILL=tests/fixtures/capacity_fill.fs
PROBE=tests/fixtures/capacity_probe.fs
LIMIT=1536            # control free space (no-overlay build)
STORE_BLOCKS=128      # the SHIPPING store; the host fake serves 64, so this bound is computed not probed
SAFE=3
CAP=40
WORK=.auto/tmp/phprobe-$$
[ -x "$BIN" ] || { echo "BUILD FAILED: $BIN missing" >&2; exit 1; }
mkdir -p "$WORK"

base=$("$BIN" $PRE $FILL "$PROBE" 2>&1 | grep -av '^SRV ' | tail -2 | head -1 | awk '{print $1}')
case "$base" in ''|*[!0-9]*) echo "ceiling_probe: cannot read the baseline HERE" >&2; exit 1;; esac

total=0; blocks=0; high=0; stopped="the $CAP-phase cap"
for ((n=1; n<=CAP; n++)); do
    python3 tools/mkphases.py --count "$n" --out "$WORK" >/dev/null
    f="$WORK/ph$n.fsx"
    chars=$(sed 's/[\\].*$//' "$f" | tr -d '\n' | wc -c)
    add=$(( (chars + 127) / 128 ))
    if [ $((blocks + add)) -gt "$STORE_BLOCKS" ]; then stopped="the store ($((blocks + add)) > $STORE_BLOCKS blocks)"; break; fi
    out=$("$BIN" $PRE $FILL "$f" "$PROBE" 2>&1 | grep -av '^SRV ' | ./artifacts/expand)
    h=$(grep -av '^ *$' <<<"$out" | tail -1 | awk '{print $1}')
    case "$h" in ''|*[!0-9]*) stopped="phase $n failing to measure ($(tr '\n' ' ' <<<"$out" | tail -c 50))"; break;; esac
    size=$((h - base))
    [ "$size" -gt 0 ] || { stopped="phase $n compiling to nothing"; break; }
    total=$((total + size)); blocks=$((blocks + add)); high=$n
done

printf "  escalated to %d phases; stopped by %s\n" "$high" "$stopped"
printf "  HIGH SCORE: %d phases, %d B compiled, %d/%d store blocks\n" "$high" "$total" "$blocks" "$STORE_BLOCKS"
printf "  safe baseline %d phases; high score vs safe: " "$SAFE"
if [ "$high" -gt "$SAFE" ]; then printf "%d > %d PASS\n" "$high" "$SAFE"
else printf "%d <= %d FAIL\n" "$high" "$SAFE"; exit 1; fi
printf "  %d B vs control %d B: %d%% of the control\n" "$total" "$LIMIT" $(( total * 100 / LIMIT ))
[ "$total" -gt "$LIMIT" ] || { echo "  FAIL: high score does not exceed the control" >&2; exit 1; }
exit 0
