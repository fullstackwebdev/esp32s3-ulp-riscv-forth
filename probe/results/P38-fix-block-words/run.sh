#!/bin/bash
# P38 runner. Every run under timeout; no `&`, no /tmp, nothing piped through head (P37: a piped
# run hides the partial line a `timeout` kill leaves, and a hang is a data point here).
cd "$(dirname "$0")"
set -x

# ---- predictions, computed before any run ----
timeout 30 python3 predict.py > logs/predict.log 2>&1; echo "PREDICT_EXIT=$?"
timeout 30 ./build.sh > logs/build.log 2>&1; tail -4 logs/build.log

# ---- (a) compiled conditionals and loops, four nesting levels ----
timeout 30 ./artifacts/host_blocks src/boot16.fs src/exp_a.fs > logs/a.log 2>&1
echo "A_EXIT=$?"

# ---- (b)(c)(d) the driver: token stream, BLOCK, SAVE, measured sp ----
timeout 30 ./artifacts/p38_test src/boot16.fs src/blocks.fs > logs/bcd.log 2>&1
echo "BCD_EXIT=$?"

# ---- (e) overlap: the dictionary grown into the buffer, at the 4096 pool ----
timeout 30 ./artifacts/p38_test src/boot16.fs src/blocks.fs grow > logs/e.log 2>&1
echo "E_EXIT=$?"

# ---- (e) again, as P33's own host build had it: MEMSZ=2304, the layer's real growth ----
timeout 30 ./artifacts/host_blocks_p33mem src/boot16.fs src/blocks.fs src/test_block.fs \
    > logs/e_p33mem.log 2>&1
echo "E_P33MEM_EXIT=$?"

# ---- (e) at P33's pool with the longer test file: HERE > 1792, so the first fetch is refused ----
timeout 30 ./artifacts/host_blocks_p33mem src/boot16.fs src/blocks.fs src/exp2.fs \
    > logs/e_p33mem_exp2.log 2>&1
echo "E_P33MEM_EXP2_EXIT=$?"

# ---- P33's four execution cases, on P33's own test file, unmodified ----
timeout 30 ./artifacts/host_blocks src/boot16.fs src/blocks.fs src/test_block.fs \
    > logs/p33_cases.log 2>&1
echo "P33_CASES_EXIT=$?"

# ---- P33/P37's 58-test suite: probe/uforth/host_test.c, unmodified, built here ----
HERE_DIR=$PWD
timeout 30 nice -n 10 gcc -DHOST -std=c99 -Wall -Wextra \
    -o artifacts/uforth_test ../../uforth/host_test.c 2>&1 | tee logs/suite_build.log
echo "SUITE_BUILD_EXIT=${PIPESTATUS[0]}"
cd ../../uforth && timeout 30 "$HERE_DIR/artifacts/uforth_test" > "$HERE_DIR/logs/suite.log" 2>&1
echo "SUITE_EXIT=$?"
cd "$HERE_DIR"

# ---- P37's wrapper end-to-end file, on the fixed layer (8 checks) ----
timeout 30 ./artifacts/host_blocks src/boot16.fs src/blocks.fs src/exp2.fs > logs/p37_wrapper.log 2>&1
echo "P37_WRAPPER_EXIT=$?"
