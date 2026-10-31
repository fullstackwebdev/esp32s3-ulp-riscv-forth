#!/usr/bin/env bash
# run.sh — the acceptance surface: deterministic work counts, not wall-clock.
#
#   ./bench/run.sh            compare against bench/baseline.txt
#   ./bench/run.sh --freeze   rewrite the baseline (a deliberate act, not a reflex)
#
# WHAT IS MEASURED, and why these units:
#   result    each workload prints one checksum; a wrong answer is a failure, not a slow pass
#   DISP      dispatches executed, from the engine's own counter (-DP42_COUNT). This is THE portable
#             metric: it is identical on any host, so it does not drift with machine load, and it moves
#             only when the engine's work per operation changes. Wall-clock is recorded but never compared.
#   limits    the depth ladder (deepest legal recursion, then the refusal) and the free bytes, which are
#             exact integers and therefore the only things an acceptance test can compare for equality.
#
# GUARDRAIL: DISP is measured with the prelude already compiled, so every number here is the workload's
# cost ON TOP OF a constant baseline (~261 dispatches). The baseline run below subtracts it; comparing raw
# DISP would make every workload inherit unrelated changes to the prelude.
set -euo pipefail
cd "$(dirname "$0")/.."
export IDF_PATH=/home/user/research/esp32/esp-idf
# shellcheck disable=SC1091
. "$IDF_PATH/export.sh" >/dev/null 2>&1 || true

CC=${CC:-gcc}
# GUARDRAIL: MEMSZ is 2048 here, not the shipping 1200. The workloads need room to be written (the shipping
# image leaves 154 B of app space), and this binary measures the ENGINE, not the image's fit. The block
# window therefore sits at 2048-128 = 1920, which is why nothing may assume 1072.
$CC -O2 -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=2048 -DP42_COUNT \
    -DP33_BLOCK -DBLKPRIM -DBLKSZ=128 -DBLK_MB=4 -o artifacts/bench src/uforth.c
$CC -Os -o artifacts/expand tools/expand.c

run() {  # run <file> -> "checksum disp"
    local out
    out=$(timeout 120 ./artifacts/bench src/p39_prelude.fs "$1" 2>&1 \
          | grep -a -v ': error$' | grep -a -v '^SRV ' | ./artifacts/expand || true)
    local disp; disp=$(printf '%s' "$out" | sed -n 's/^DISP \([0-9]*\)$/\1/p' | tail -1)
    local result; result=$(printf '%s' "$out" | grep -a -v '^DISP ' | tr -d '\n')
    printf '%s %s' "$result" "${disp:-0}"
}

base=$(timeout 60 ./artifacts/bench src/p39_prelude.fs 2>&1 | grep -a -v '^SRV ' \
       | ./artifacts/expand | sed -n 's/^DISP \([0-9]*\)$/\1/p' | tail -1)
base=${base:-0}
echo "prelude baseline: $base dispatches"
echo
printf '%-12s %-14s %-10s\n' workload result "dispatches"
printf '%-12s %-14s %-10s\n' -------- ------ ----------
: > /dev/null
rows=()
for f in bench/arith.fs bench/matrix.fs bench/recursion.fs bench/memory.fs bench/depth.fs; do
    name=$(basename "$f" .fs)
    read -r result disp <<<"$(run "$f")"
    # GUARDRAIL: a workload that ENDS in a deliberate error never reaches the exit-time DISP print, so its
    # dispatch count does not exist. Recording it as "-" keeps the comparison honest instead of storing a
    # number that is really "0 minus the baseline".
    if [ "${disp:-0}" = "0" ]; then net="-"; else net=$((disp - base)); fi
    printf '%-12s %-14s %-10s\n' "$name" "$result" "$net"
    rows+=("$name $result $net")
done

if [ "${1:-}" = "--freeze" ]; then
    {
        echo "# bench baseline — freeze with ./bench/run.sh --freeze ONLY when a change is understood."
        echo "# result: the checksum the workload must produce (exact)"
        echo "# disp:   dispatches above the prelude baseline (exact; a change means the engine's work changed)"
        echo "prelude_base $base"
        printf '%s\n' "${rows[@]}"
    } > bench/baseline.txt
    echo; echo "frozen -> bench/baseline.txt"
    exit 0
fi

fail=0
[ -f bench/baseline.txt ] || { echo "no bench/baseline.txt (run with --freeze once)" >&2; exit 2; }
while read -r name result disp; do
    case "$name" in \#*|prelude_base|"") continue ;; esac
    got=$(printf '%s\n' "${rows[@]}" | awk -v n="$name" '$1==n {print $2" "$3}')
    [ -n "$got" ] || { echo "MISSING $name" >&2; fail=1; continue; }
    if [ "$disp" = "-" ]; then
        gres=${got% *}
        if [ "$gres" != "$result" ]; then echo "FAIL $name: result [$result] now [$gres]" >&2; fail=1;
        else echo "PASS $name"; fi
        continue
    fi
    if [ "$got" != "$result $disp" ]; then
        echo "FAIL $name: baseline [$result $disp] now [$got]" >&2; fail=1
    else
        echo "PASS $name"
    fi
done < bench/baseline.txt
exit $fail
