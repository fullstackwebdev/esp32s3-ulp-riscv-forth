#!/usr/bin/env bash
# flash_safe.sh — measure, refuse if the pool is over budget, then flash.
#
# GUARDRAIL: `idf.py build` does not report pool usage (F-77) and the link succeeds far past the budget,
# so an over-budget image builds, flashes and RUNS until the ULP C stack, which lives above the pool,
# overflows into .bss. The symptom is corrupted interpreter state (a bare `?`, definitions that vanish),
# not a build error — I flashed 7 984 B that way and lost a debugging cycle to it. This gate makes the
# size check part of flashing instead of part of remembering.
set -euo pipefail
POOL=7856
ELF=build/esp-idf/main/ulp_main/ulp_main.elf
export IDF_PATH=/home/user/research/esp32/esp-idf
# shellcheck disable=SC1091
. "$IDF_PATH/export.sh" >/dev/null 2>&1
TOT=$(riscv32-esp-elf-size "$ELF" | awk 'NR==2{print $1+$2+$3}')
echo "pool: $TOT / $POOL  (stack reserve $((8192 - TOT)) B)"
if [ "$TOT" -gt "$POOL" ]; then
    echo "REFUSING to flash: over budget by $((TOT - POOL)) B — lower MEMSZ or free bytes first" >&2
    exit 1
fi
exec idf.py -p /dev/ttyACM1 flash
