# P16 environment: board lock + ESP-IDF, as used for every command in RESULT.md.
# GUARDRAIL: the lock lives in the same shell as the device commands, and flashing goes to
# /dev/ttyACM1 (UART0/CH343) — /dev/ttyACM0 is the native USB-JTAG port that wedged in P06
# and cannot force download mode.
exec 9>>"$(dirname "$0")/../.board.lock"
flock -n 9 || { echo "BLOCKED: board busy"; exit 3; }
export IDF_PATH=/home/user/research/esp32/esp-idf
. "$IDF_PATH/export.sh" >/dev/null 2>&1
