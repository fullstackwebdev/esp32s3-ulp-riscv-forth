#!/bin/bash
# P36 host execution: the same engine source, host gcc, against the fake block server (P34's).
set -x
cd "$(dirname "$0")"
timeout 300 nice -n 10 gcc -O1 -std=gnu99 -DHOST -DP34_NOPAGE -DP34_FAR \
    -DMEMSZ=4096 -DTIBSZ=128 -DSD=16 -DNTSK=3 -Isrc -o artifacts/host_seg src/uforth.c \
    > logs/host_build.log 2>&1
echo "BUILD_EXIT=$?"
