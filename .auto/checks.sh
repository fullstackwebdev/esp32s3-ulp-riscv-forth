#!/usr/bin/env bash
# .auto/checks.sh — correctness backpressure. The metric never counts if this fails.
#
# Two gates:
#   1. the host suite (12 checks, includes the storage semantics, blocks, errors, ring drain)
#   2. the benchmark surface: checksums must be IDENTICAL. DISP (dispatch counts) is also compared, which
#      is deliberate: a byte win that changes the token stream has to be a deliberate, explained change,
#      not a side effect. If a legitimate idea changes DISP, re-freeze the baseline in the same commit.
set -euo pipefail
cd "$(dirname "$0")/.."

probe/repl/tests/run.sh > .auto/tmp/tests.log 2>&1 || { echo "SUITE FAILED:"; tail -30 .auto/tmp/tests.log; exit 1; }
pass=$(grep -cE '^PASS' .auto/tmp/tests.log || true)
[ "$pass" -ge 12 ] || { echo "SUITE RAN $pass PASSES, EXPECTED 12:"; tail -20 .auto/tmp/tests.log; exit 1; }

probe/repl/bench/run.sh > .auto/tmp/bench.log 2>&1 || { echo "BENCH FAILED:"; tail -20 .auto/tmp/bench.log; exit 1; }
grep -qE '^FAIL' .auto/tmp/bench.log && { echo "BENCH COMPARISON FAILED:"; grep -E '^FAIL' .auto/tmp/bench.log; exit 1; }
echo "checks: suite $pass/$pass PASS, bench identical"
