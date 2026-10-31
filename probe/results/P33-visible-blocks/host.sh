#!/bin/bash
# P33 host execution: the same engine source, built by host gcc against the fake mailbox server.
set -x
cd "$(dirname "$0")"
timeout 300 nice -n 10 gcc -O1 -std=gnu99 -DHOST -DP33_NOPAGE -DP33_BLOCK \
    -DMEMSZ=2304 -DTIBSZ=128 -DSD=16 -DNTSK=3 -Isrc -o artifacts/host_blocks src/uforth.c \
    2>&1 | tee logs/host_build.log
echo "BUILD_EXIT=${PIPESTATUS[0]}"
