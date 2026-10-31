#!/bin/bash
# P12 build driver: same shape as P01's run_idf.sh (tmux + nice + timeout, log to logs/).
# Only the project name and the log file differ; the measuring recipe is unchanged.
set -x
cd "$(dirname "$0")"
export IDF_PATH=/home/user/research/esp32/esp-idf
. $IDF_PATH/export.sh >/dev/null 2>&1 || { echo "BLOCKED: export.sh failed"; exit 1; }
cd idfproj
timeout 300 nice -n 10 idf.py set-target esp32s3 || { echo "BLOCKED: set-target failed"; exit 1; }
timeout 300 nice -n 10 idf.py build
echo "EXIT=$?"
