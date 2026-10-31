#!/bin/bash
# P29 driver: host-only link. tmux + nice + timeout, per the probe brief.
set -x
cd "$(dirname "$0")"
export IDF_PATH=/home/user/research/esp32/esp-idf
. $IDF_PATH/export.sh >/dev/null 2>&1 || { echo "BLOCKED: export.sh failed"; exit 1; }
MEMSZ=${1:-908}
timeout 300 nice -n 10 python3 p29_build.py "$MEMSZ"
echo "EXIT=$?"
