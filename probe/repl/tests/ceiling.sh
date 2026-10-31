#!/bin/bash
# ceiling.sh — does paging raise the CEILING? Nine phases, each filled to the per-phase window, against the
# no-overlay control. This replaces the first flagship's +4 %: that program averaged 268 B per phase, so it was
# barely bigger than the control and tested a small program rather than the claim.
#
# GUARDRAIL: each phase is measured in a FRESH process (fill + one phase). Loading them one after another
# accumulates them in the overlay area and overruns the dictionary, which surfaces as a resident word vanishing.
set -u
cd "$(dirname "$0")/.." || exit 1
BIN=artifacts/host_cap
PRE="src/p39_prelude.fs src/p39b_overlay.fs"
FILL=tests/fixtures/capacity_fill.fs
LIMIT=1536                # the control's free space, measured on the no-overlay build
[ -x "$BIN" ] || { echo "BUILD FAILED: $BIN missing" >&2; exit 1; }

base=$("$BIN" $PRE $FILL tests/fixtures/capacity_probe.fs 2>&1 | grep -av '^SRV ' | tail -2 | head -1 | awk '{print $1}')
case "$base" in ''|*[!0-9]*) echo "ceiling: cannot read the baseline HERE" >&2; exit 1;; esac

fail=0; total=0; n=0
while read -r phase want; do
    out=$("$BIN" $PRE $FILL "tests/${phase}.fsx" tests/fixtures/capacity_probe.fs 2>&1 | grep -av '^SRV ' | ./artifacts/expand)
    h=$(grep -av '^ *$' <<<"$out" | tail -1 | awk '{print $1}')
    got=$(grep -av '^ *$' <<<"$out" | sed -n '1p' | tr -cd '0-9')
    case "$h" in ''|*[!0-9]*) echo "  $phase: FAILED to measure: $(tr '\n' ' ' <<<"$out" | tail -c 60)" >&2; fail=1; continue;; esac
    size=$((h - base)); total=$((total + size)); n=$((n + 1))
    if [ "$got" = "$want" ]; then printf "  %s: %4d B  numbers ok\n" "$phase" "$size"
    else printf "  %s: %4d B  NUMBERS WRONG (want %s got %s)\n" "$phase" "$size" "$want" "$got" >&2; fail=1; fi
done < <(grep -v '^\\' tests/ceiling_expect.txt)

[ "$n" -gt 0 ] || { echo "ceiling: no phases measured" >&2; exit 1; }
printf "  total %d B across %d window-sized phases vs control %d B: " "$total" "$n" "$LIMIT"
if [ "$total" -gt "$LIMIT" ]; then
    mult=$(( total * 100 / LIMIT ))
    echo "PASS (${mult}% of the control, +$(( mult - 100 ))%)"
    if [ "$mult" -ge 200 ]; then echo "  VERDICT: paging raises the ceiling by $(( mult / 100 ))x - the machinery earns its place"
    elif [ "$mult" -ge 150 ]; then echo "  VERDICT: above 1.5x - marginal, ship only if the program needs it"
    else echo "  VERDICT: under 1.5x - bank the resident toll"; fi
else
    echo "FAIL (does not exceed the control)"; fail=1
fi
exit "$fail"
