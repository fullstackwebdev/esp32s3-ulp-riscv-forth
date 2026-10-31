#!/bin/bash
# P37: every run under a hard timeout — a hang is the expected failure mode, not a surprise.
# HOST ONLY: nothing here opens /dev/ttyACM*.
cd "$(dirname "$0")"
set -x
timeout 30 ./build.sh > logs/build.log 2>&1; tail -1 logs/build.log
timeout 30 ./build_trace.sh > logs/build_trace.log 2>&1; tail -1 logs/build_trace.log
timeout 10 ./artifacts/host_blocks src/boot37.fs src/exp1a.fs            # exp 1, terminating half
timeout 5  ./artifacts/host_blocks src/boot37.fs src/exp1b.fs            # exp 1, the hang (expected)
timeout 5  ./artifacts/host_blocks src/boot16.fs src/exp_l.fs            # P33's prelude, the defect
timeout 25 ./artifacts/host_blocks src/boot37.fs src/blocks37.fs src/exp2.fs   # exp 2, real wrapper
timeout 25 ./artifacts/host_blocks src/boot37.fs src/blocks37.fs src/exp3.fs   # exp 3, Forth bound
