#!/usr/bin/env bash
# flash_safe.sh — measure, refuse if the pool is over budget, then flash.
#
# GUARDRAIL: `idf.py build` does not report pool usage (F-77) and the link succeeds far past the budget,
# so an over-budget image builds, flashes and RUNS until the ULP C stack, which lives above the pool,
# overflows into .bss. The symptom is corrupted interpreter state (a bare `?`, definitions that vanish),
# not a build error — I flashed 7 984 B that way and lost a debugging cycle to it. This gate makes the
# size check part of flashing instead of part of remembering.
set -euo pipefail
# GUARDRAIL: POOL is a STACK RESERVE decision, not a constant. It was 7856 (= 8192 - 336), i.e. a 336 B stack reserve
# chosen before anything measured the stack. `#k` now reports the painted high-water mark: 240 B of a 324 B region, the
# same across boot, arithmetic, BLOCK, LOAD, adopt+EXECUTE, errors and 15 phases. Reserve 300 B = measured 240 + 25 %
# margin (an overflow corrupts engine state SILENTLY, so the margin stays).
#
# GUARDRAIL: the reserve is now 285 B, not 300. The hardware gate in P() (F-149: Forth may reach the 64-byte RTC GPIO
# window, with noinline + one range test) costs 12 B, and paying for it out of the 25 % margin is a deliberate, measured
# trade rather than an accident: 240 B measured high-water + 45 B margin = 285, i.e. 18.75 %. Re-run `#k` on the board
# after a change like this - it reports the painted high-water - and if it moves, the reserve moves back up.
# 8192 - 285 = 7907.
#
# 2026-11-01: back to 7892. The gate that wanted those 17 B also raised the painted stack high-water 240 -> 269, so the
# margin it borrowed was not margin at all. Measured, reverted, recorded.
# 2026-11-01 (second correction): the painted high-water is 144 B, not 240 B. The 240 figure came from an older layout and
# the "0 B free" readings in between were STALE PAINT - RTC RAM survives a reset, so #k was reporting a previous image's
# damage. With a fresh paint the stack uses 144 B of 284, so the reserve can be 200 B: 144 measured + 56 B margin (28 %).
# GUARDRAIL: at reserve 200 (POOL 7992) the stack ran INTO the image - #k read 184 of 184 B, 0 free - and the
# machine then answered `ok` to `: XX 42 ;` and `XX?` afterwards: a stack that overlaps the image corrupts dictionary
# writes silently, so it looks like a broken compiler, not a full stack. Never size the reserve from the paint alone;
# require image + reserve <= 8192 with margin to spare.
# 8192 - 260 = 7932 (260 = 144 measured + 116 margin).
POOL=7932
ELF=build/esp-idf/main/ulp_main/ulp_main.elf
export IDF_PATH=/home/user/research/esp32/esp-idf
# shellcheck disable=SC1091
. "$IDF_PATH/export.sh" >/dev/null 2>&1
TOT=$(riscv32-esp-elf-size "$ELF" | awk 'NR==2{print $1+$2+$3}')
echo "pool: $TOT / $POOL  (stack reserve $((8192 - TOT)) B, measured high-water 240 B)"
if [ "$TOT" -gt "$POOL" ]; then
    echo "REFUSING to flash: over budget by $((TOT - POOL)) B — lower MEMSZ or free bytes first" >&2
    exit 1
fi
exec idf.py -p /dev/ttyACM1 flash
