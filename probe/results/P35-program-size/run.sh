#!/bin/bash
# P35 driver: host-only, maximal MEMSZ by construction, both link conventions. tmux + nice + timeout.
set -x
cd "$(dirname "$0")"
export IDF_PATH=/home/user/research/esp32/esp-idf
. $IDF_PATH/export.sh >/dev/null 2>&1 || { echo "BLOCKED: export.sh failed"; exit 1; }
timeout 290 nice -n 10 python3 p35_build.py 270 2>&1 | tee "logs/p35_build.log"
echo "EXIT=${PIPESTATUS[0]}"
