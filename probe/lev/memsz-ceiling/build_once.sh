#!/bin/bash
# GUARDRAIL: measure the pool from the LINKED ULP ELF, never from the .obj — .bss only exists in
# the ELF, and bss is where uforth's rings/mailbox live, so an .obj-only 'size' undercounts by
# ~1.1 KB and would "prove" a ceiling that overflows RTC RAM on the chip.
#
# build_once.sh <tag> [pool_limit]
# Compiles this directory's src/ulp_repl.c with the exact flags from the probe/repl
# build.ninja C_COMPILER__ulp_main_ rule, links out.elf with the ULPs' own -T script
# (src/ulp_p39.ld: LENGTH=7856), and prints riscv32-esp-elf-size for out.elf.
set -u

TAG="${1:?usage: build_once.sh <tag>}"
LIMIT="${2:-7856}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPL="$HERE/../../repl/build/esp-idf/main/ulp_main"
CORE="$REPL/CMakeFiles/ulp_main.dir/home/user/research/esp32/esp-idf/components/ulp/ulp_riscv/ulp_core"
OUT="$HERE/out/$TAG"

export IDF_PATH=/home/user/research/esp32/esp-idf
# shellcheck disable=SC1090
. "$IDF_PATH/export.sh" >/dev/null 2>&1

mkdir -p "$OUT" || exit 1

# GUARDRAIL: riscv32-esp-elf-gcc must come from the IDF-exported toolchain (esp-14.2.0), not the
# distro riscv64 cross — the target triples differ and rv32imc code will not link.
nice -n 15 timeout 300 riscv32-esp-elf-gcc \
    -DIS_ULP_COCPU -DULP_RISCV_REGISTER_OPS \
    -Os -march=rv32imc_zicsr_zifencei -mdiv -fdata-sections -ffunction-sections \
    -o "$OUT/ulp_repl.o" -c "$HERE/src/ulp_repl.c" || { echo "COMPILE FAILED"; exit 1; }

# GUARDRAIL: link with -T src/ulp_p39.ld (LENGTH 7856 = 8176 - 320 B C stack). The stock
# ulp_riscv.ld sets LENGTH 8176 and would let a too-large MEMSZ link clean, then the C stack
# grows down into the dictionary on silicon (P21).
nice -n 15 timeout 300 riscv32-esp-elf-gcc \
    -march=rv32imc_zicsr_zifencei --specs=nano.specs --specs=nosys.specs \
    -nostartfiles -Wl,--gc-sections -Wl,--no-warn-rwx-segments \
    -Wl,-Map="$OUT/out.map" \
    -T "$HERE/src/ulp_p39.ld" \
    /home/user/research/esp32/esp-idf/components/ulp/ld/esp32s3.peripherals.ld \
    -o "$OUT/out.elf" \
    "$OUT/ulp_repl.o" \
    "$CORE/ulp_riscv_vectors.S.obj" "$CORE/start.S.obj" \
    "$CORE/ulp_riscv_adc.c.obj" "$CORE/ulp_riscv_lock.c.obj" \
    "$CORE/ulp_riscv_uart.c.obj" "$CORE/ulp_riscv_print.c.obj" \
    "$CORE/ulp_riscv_i2c.c.obj" "$CORE/ulp_riscv_utils.c.obj" \
    "$CORE/ulp_riscv_touch.c.obj" "$CORE/ulp_riscv_gpio.c.obj" \
    "$CORE/ulp_riscv_interrupt.c.obj" \
    2>"$OUT/link.err"
LINK_RC=$?

if [ $LINK_RC -ne 0 ]; then
    echo "LINK FAILED (rc=$LINK_RC)"
    cat "$OUT/link.err"
    exit 2
fi

riscv32-esp-elf-size "$OUT/out.elf" | tee "$OUT/size.txt"
read -r TEXT DATA BSS _ < <(riscv32-esp-elf-size "$OUT/out.elf" | awk 'NR==2{print $1, $2, $3}')
TOTAL=$(( TEXT + DATA + BSS ))
FITS="y"; [ "$TOTAL" -gt "$LIMIT" ] && FITS="n"
printf 'MEMSZ_TOTAL text=%d data=%d bss=%d total=%d limit=%d fits=%s\n' \
    "$TEXT" "$DATA" "$BSS" "$TOTAL" "$LIMIT" "$FITS"
