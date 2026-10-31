#!/bin/bash
# P20 variant builds: compile + link only, reusing the flags IDF generated in the A build.
# GUARDRAIL: the MLM environment must come from export.sh, not from a hardcoded toolchain path —
# riscv32-esp-elf-size/objcopy live in the toolchain dir that only export.sh puts on PATH.
set -x
cd "$(dirname "$0")"
export IDF_PATH=/home/user/research/esp32/esp-idf
. $IDF_PATH/export.sh >/dev/null 2>&1 || { echo "BLOCKED: export.sh failed"; exit 1; }
timeout 300 nice -n 10 python3 p20_variants.py
echo "EXIT=$?"
