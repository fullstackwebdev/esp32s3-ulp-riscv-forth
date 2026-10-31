#!/bin/bash
# P34 driver: RISC-V link of D (delta base) and F (D minus frames/table/fetch, plus FAR-XFER).
set -x
cd "$(dirname "$0")"
export IDF_PATH=/home/user/research/esp32/esp-idf
. $IDF_PATH/export.sh >/dev/null 2>&1 || { echo "BLOCKED: export.sh failed"; exit 1; }
timeout 300 nice -n 10 python3 p34_build.py D 908 2>&1 | tee logs/p34_D.log
timeout 300 nice -n 10 python3 p34_build.py F 908 2>&1 | tee logs/p34_F.log
echo "EXIT=$?"
