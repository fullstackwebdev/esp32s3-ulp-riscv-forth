#!/usr/bin/env bash
# run.sh — regression suite for the SHIPPING engine (src/uforth.c), not the prototype.
#
# Builds the host binary from the same source the ULP runs, executes tests/suite.fs, and diffs the output
# against tests/expected.txt.
#
# GUARDRAIL: do not load src/line.fs here. It is P39's demo line ("2 3 + 4 * ."), so it PRINTS 20 into the
# golden output; including it makes the suite fail for a reason unrelated to any change, and the obvious
# "fix" is to regenerate the golden file — which is how a test suite quietly stops testing anything.
set -euo pipefail
cd "$(dirname "$0")/.."
export IDF_PATH=/home/user/research/esp32/esp-idf
# shellcheck disable=SC1091
. "$IDF_PATH/export.sh" >/dev/null 2>&1 || true

CC=${CC:-gcc}
gcc -O2 -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=2048 \
    -o artifacts/host_suite src/uforth.c

# GUARDRAIL: the engine now emits ONE BYTE per message (src/msg_codes.h), so the raw stream is not the
# operator's transcript. Both sides are piped through tools/expand.c, which includes the SAME
# src/msg_expand.h the bridge uses — a filter with its own mapping would test the copy, not the machine (R9).
gcc -Os -o artifacts/expand tools/expand.c || exit 1
got=$(timeout 30 ./artifacts/host_suite src/p39_prelude.fs tests/suite.fs 2>&1 | ./artifacts/expand)
want=$(cat tests/expected.txt)
# Every green suite prints the standing metric, so progress is measured in the same units every time.
./countdown.sh || true

# The task-table bound is its own check: it deliberately errors, and an error aborts a load.
raw_ntsk=$(timeout 30 ./artifacts/host_suite src/p39_prelude.fs tests/ntsk.fs 2>&1 | ./artifacts/expand || true)
# The host loader's own "<file>:<line>: error" line is a driver diagnostic, not machine output, so it is
# stripped for the comparison — but its PRESENCE is asserted separately, because "the load aborted on the
# third SPAWN" is half of what this test proves.
printf '%s' "$raw_ntsk" | grep -q ': error$' || { echo "FAIL  ntsk.fs did not abort on the third SPAWN" >&2; exit 1; }
got_ntsk=$(printf '%s' "$raw_ntsk" | grep -v ': error$')
want_ntsk=$(cat tests/ntsk.expected)
if [ "$got_ntsk" != "$want_ntsk" ]; then
    echo "FAIL  ntsk.fs: want '$want_ntsk', got '$got_ntsk'" >&2
    exit 1
fi
echo "PASS  ntsk.fs refuses a third task with '$got_ntsk'"

if [ "$got" = "$want" ]; then
    echo "PASS  suite.fs matches expected.txt (${#got} bytes of output)"
else
    echo "FAIL  suite output differs" >&2
    echo "  want: $want" >&2
    echo "  got : $got" >&2
    exit 1
fi
