#!/bin/bash
# flagship.sh — the 6-phase program: per-phase size, per-phase numbers, and the total against the control.
#
# GUARDRAIL: every phase is measured in a FRESH process (fill + one phase). Loading phases one after another in a
# single process accumulates them in the overlay area - it does not model the product, where a phase is discarded
# before the next loads - and it overruns the dictionary, which surfaces as a resident word vanishing (measured:
# vb1? in phase D, with phases A..C already resident).
#
# Numbers are checked in the pairs that fit together: B+C (histogram + verify), D+E (paged write + verify),
# B+F (histogram + formatted report).
set -u
cd "$(dirname "$0")/.." || exit 1
BIN=artifacts/host_cap
PRE="src/p39_prelude.fs src/p39b_overlay.fs"
FILL=tests/fixtures/capacity_fill.fs
COMMON=tests/fixtures/flagship_common.fs
LIMIT=1536            # the control's free space (measured, no-overlay build)
[ -x "$BIN" ] || { echo "BUILD FAILED: $BIN missing" >&2; exit 1; }

base=$("$BIN" $PRE "$COMMON" tests/fixtures/free_probe.fs 2>&1 | grep -av '^SRV ' | tr -cd '0-9' | tail -c 4)
case "$base" in ''|*[!0-9]*) base=$("$BIN" $PRE "$COMMON" tests/fixtures/free_probe.fs 2>&1 | grep -av '^SRV ' | tail -1);; esac
here0=$("$BIN" $PRE "$COMMON" tests/fixtures/capacity_probe.fs 2>&1 | grep -av '^SRV ' | tail -2 | head -1 | awk '{print $1}')
case "$here0" in ''|*[!0-9]*) echo "flagship: cannot read the baseline HERE" >&2; exit 1;; esac
printf "  resident scaffold + manager: HERE %s\n" "$here0"

fail=0; total=0
run_fresh() { "$BIN" $PRE "$COMMON" $FILL "$@" 2>&1 | grep -av '^SRV ' | ./artifacts/expand; }

for f in a:flagship_a b:flagship_b c:flagship_c d:flagship_d e:flagship_e f:flagship_f; do
    name=${f%%:*}; file=tests/${f##*:}.fsx
    [ -f "$file" ] || continue
    pre="$FILL"; [ "$name" = a ] && pre=""        # phase A fills the window itself
    out=$("$BIN" $PRE "$COMMON" $pre "$file" tests/fixtures/capacity_probe.fs 2>&1 | grep -av '^SRV ')
    h=$(grep -av '^ *$' <<<"$out" | tail -1 | awk '{print $1}')
    case "$h" in ''|*[!0-9]*) echo "  phase ${name^^}: FAILED to measure: $(tr '\n' ' ' <<<"$out" | tail -c 70)" >&2; fail=1; continue;; esac
    size=$((h - here0)); total=$((total + size))
    printf "  phase %s: %4d B compiled\n" "${name^^}" "$size"
done

check() {  # check <label> <command...> <expected>
    local label=$1 want=$2 got
    shift 2
    got=$(run_fresh "$@" | tr -d '\n' | tr -cd '0-9')
    if [ "$got" = "$want" ]; then printf "  %s: %s OK\n" "$label" "$want"
    else printf "  %s: FAIL (want %s, got '%s')\n" "$label" "$want" "$got" >&2; fail=1; fi
}
check "phase A numbers" "81280127" tests/flagship_a.fsx
check "histogram + verify (B,C)" "81288"      tests/flagship_b.fsx tests/flagship_c.fsx
check "paged write + verify (D,E)" "0"        tests/flagship_d.fsx tests/flagship_e.fsx
check "histogram report (B,F)"     "008008008008008008008008008008008008008008008008" tests/flagship_b.fsx tests/flagship_f.fsx

printf "  total %d B across six phases vs control %d B: " "$total" "$LIMIT"
if [ "$total" -gt "$LIMIT" ]; then
    pct=$(( (total - LIMIT) * 100 / LIMIT ))
    echo "PASS (+${pct}%)"
    if [ "$total" -lt $(( LIMIT * 3 / 2 )) ]; then
        echo "  NOTE: under 1.5x the control - by the agreed rule this earns banking, not shipping"
    fi
else
    echo "FAIL (does not exceed the control)"; fail=1
fi
exit "$fail"
