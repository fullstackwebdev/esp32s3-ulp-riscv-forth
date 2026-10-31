#!/bin/bash
# P30 driver: host-only link, per variant. tmux + nice + timeout, per the probe brief.
set -x
cd "$(dirname "$0")"
export IDF_PATH=/home/user/research/esp32/esp-idf
. $IDF_PATH/export.sh >/dev/null 2>&1 || { echo "BLOCKED: export.sh failed"; exit 1; }
V=${1:-A}
MEMSZ=${2:-908}
timeout 300 nice -n 10 python3 p30_build.py "$V" "$MEMSZ" 2>&1 | tee "logs/p30_${V}.log"
echo "EXIT=${PIPESTATUS[0]}"
