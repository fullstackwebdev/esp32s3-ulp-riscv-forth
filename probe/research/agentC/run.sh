#!/usr/bin/env bash
# run.sh — agentC: measure the real data-stack high-water mark for every workload, then
# rebuild the same source at SD 8 / 16 / 32 and record what each step costs.
#
# GUARDRAIL: SD is varied only in this *measurement* build; the peak is read from the SD-256 build,
# never from the SD-16 one. With SD 16 a program that pushes past 16 still increments sp (the index is
# masked, not the counter), so the peak is honest — but its VALUES are already corrupted, so a recursion
# whose control flow depends on them can take a different path and under-report the depth. Measure big.
set -euo pipefail
cd "$(dirname "$0")"
MEMSZ=1704
BASE="-Os -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=$MEMSZ"
CC=gcc

build() {  # build <out> <extra flags...>
    local out=$1; shift
    timeout 300 $CC $BASE "$@" -o "out/$out" src/uforth.c
}

run() {    # run <bin> <label> <fs files...>
    local bin=$1 label=$2; shift 2
    echo "--- $label"
    timeout 300 "out/$bin" src/p39_prelude.fs "$@" 2>&1 | tee "out/$label.log" | tail -3
    echo
}

# ---- 1. the measurement build: SD 256 so the peak cannot be capped, and NTSK 3 so the 3-task
#         workload actually runs (the shipping NTSK 2 refuses the third SPAWN by design).
build hwm256_sd256_ntsk3 -DSD=256 -DNTSK=3
run hwm256_sd256_ntsk3 A_suite  tests/suite.fs
run hwm256_sd256_ntsk3 B_fib    work/w_fib.fs
run hwm256_sd256_ntsk3 C_tasks  work/w_tasks.fs
run hwm256_sd256_ntsk3 D_deep   work/w_deep.fs

# ---- 2. control: the FIFTEEN-cell build, asked the same questions. If a row's peak is above 16 this
#         build is already aliasing; the output values are the proof, the HWM line is the coincidence.
build hwm16 -DSD=16 -DNTSK=3
run hwm16 SD16_A_suite tests/suite.fs
run hwm16 SD16_B_fib   work/w_fib.fs
run hwm16 SD16_C_tasks work/w_tasks.fs
run hwm16 SD16_D_deep  work/w_deep.fs

# ---- 3. sizing: the same binary at the three candidate SDs, reporting sizeof(VM) from the assert's own
#         formula. pool cost = (vm_live + NTSK task records) x sizeof(VM).
for sd in 8 16 32; do
    build "size_sd$sd" -DSD=$sd -DNTSK=3
    printf 'SD=%-2s ' "$sd"
    timeout 300 "out/size_sd$sd" src/p39_prelude.fs work/w_deep.fs 2>&1 >/dev/null | tail -1
done
