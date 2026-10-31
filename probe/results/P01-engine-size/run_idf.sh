#!/bin/bash
set -x
export IDF_PATH=/home/user/research/esp32/esp-idf
. $IDF_PATH/export.sh >/dev/null 2>&1 || { echo "BLOCKED: export.sh failed"; exit 1; }
cd "$(dirname "$0")/idfproj"
timeout 300 nice -n 10 idf.py set-target esp32s3 || { echo "BLOCKED: set-target failed"; exit 1; }
timeout 900 nice -n 10 idf.py build
echo "EXIT=$?"
