#!/usr/bin/env bash
# verify.sh — host-suite check for one engine shape, using the exact command line the task names.
#   ./verify.sh <shape-name> [extra -D flags ...]
# GUARDRAIL: the host build proves LOGIC only (R8). A green row here says the dispatcher still executes
# the same program; it says nothing about the ULP's timing, and the byte numbers come from measure.sh.
set -uo pipefail
cd "$(dirname "$0")"
N=$1; shift
mkdir -p out
if ! timeout 300 gcc -Os -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=1704 \
        "$@" -o "out/host_$N" src/uforth.c; then
    printf '%-14s BUILD-FAIL\n' "$N"; exit 1
fi
got=$(timeout 60 "./out/host_$N" src/p39_prelude.fs tests/suite.fs 2>&1)
want=$(cat tests/expected.txt)
raw_ntsk=$(timeout 60 "./out/host_$N" src/p39_prelude.fs tests/ntsk.fs 2>&1)
got_ntsk=$(printf '%s' "$raw_ntsk" | grep -v ': error$')
want_ntsk=$(cat tests/ntsk.expected)
# wild.fs is the TASK 2 semantic check: the checked accessors must still answer a wild address with
# junk/0 after the check moved to the call sites. Same output for every shape is the pass condition.
wild=$(timeout 60 "./out/host_$N" src/p39_prelude.fs tests/wild.fs 2>&1)
want_wild=$(cat tests/wild.expected)
suite=PASS; [ "$got" = "$want" ] || suite=FAIL
wildr=PASS; [ "$wild" = "$want_wild" ] || wildr=FAIL
ntsk=PASS
printf '%s' "$raw_ntsk" | grep -q ': error$' || ntsk=FAIL
[ "$got_ntsk" = "$want_ntsk" ] || ntsk=FAIL
printf '%-14s suite=%s ntsk=%s wild=%s  output=%s\n' "$N" "$suite" "$ntsk" "$wildr" "$got"
[ "$suite" = PASS ] && [ "$ntsk" = PASS ] && [ "$wildr" = PASS ]
