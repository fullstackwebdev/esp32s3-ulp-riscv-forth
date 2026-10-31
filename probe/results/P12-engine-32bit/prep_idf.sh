#!/bin/bash
# P12: configure-only step (set-target), run in tmux ahead of the code edits so that the
# 15-minute box is not spent waiting for a configure that does not depend on the sources.
set -x
cd "$(dirname "$0")"
export IDF_PATH=/home/user/research/esp32/esp-idf
. $IDF_PATH/export.sh >/dev/null 2>&1 || { echo "BLOCKED: export.sh failed"; exit 1; }
cd idfproj
timeout 300 nice -n 10 idf.py set-target esp32s3
echo "EXIT=$?"
