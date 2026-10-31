#!/bin/bash
# P39 one run: board lock, keep the image that gets flashed, flash over /dev/ttyACM1, capture UART0.
# GUARDRAIL: the lock is taken in THIS shell (fd 9), the same shell that touches the device — a lock
# taken in a different shell is not held while esptool runs, which is how a board gets two writers.
exec 9>../.board.lock
flock -n 9 || { echo "BLOCKED: board busy"; exit 3; }
cd "$(dirname "$0")"
export IDF_PATH=/home/user/research/esp32/esp-idf
. "$IDF_PATH/export.sh" >/dev/null 2>&1 || { echo "BLOCKED: export.sh failed"; exit 1; }

# the image we flash, plus its flash_args, kept as artifacts
cp build/p39_first_chip_run.bin artifacts/p39_first_chip_run.bin
cp build/flash_args artifacts/flash_args
cp build/esp-idf/main/ulp_main/ulp_main.bin artifacts/ulp_main.bin
cp build/esp-idf/main/ulp_main/ulp_main.elf artifacts/ulp_main.elf
cp build/esp-idf/main/ulp_main/ulp_main.map artifacts/ulp_main.map
cat artifacts/flash_args

echo "--- chip-id (recovery path, must answer before flashing) ---"
timeout 30 esptool -p /dev/ttyACM1 chip-id || { echo "BLOCKED: no chip on /dev/ttyACM1"; exit 4; }

echo "--- flash ---"
timeout 120 idf.py -p /dev/ttyACM1 -b 460800 flash 2>&1 | tail -15
echo "FLASH_EXIT=${PIPESTATUS[0]}"

echo "--- capture (20 s, sends 'g' at READY) ---"
timeout 20 python3 capture.py /dev/ttyACM1 logs/run.log
echo "CAPTURE_EXIT=$?"
