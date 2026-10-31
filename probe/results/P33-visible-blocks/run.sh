#!/bin/bash
# P33 driver: host-only link of variant E. tmux + nice + timeout, per the probe brief.
set -x
cd "$(dirname "$0")"
export IDF_PATH=/home/user/research/esp32/esp-idf
. $IDF_PATH/export.sh >/dev/null 2>&1 || { echo "BLOCKED: export.sh failed"; exit 1; }
V=${1:-E}
MEMSZ=${2:-1420}
timeout 300 nice -n 10 python3 p33_build.py "$V" "$MEMSZ" 2>&1 | tee "logs/p33_${V}.log"
echo "EXIT=${PIPESTATUS[0]}"
