#!/bin/bash
# measure.sh <srcdir> <outdir> [extra -D flags ...]
# Compiles every ULP source with the EXACT flags recorded in
# probe/repl/build/esp-idf/main/ulp_main/compile_commands.json + build.ninja, then links with the
# same LINK_FLAGS and prints the section sizes that make up the RTC pool usage.
# Read-only against everything outside this directory; writes only under <outdir>.
set -u
SRC=${1:?srcdir}; OUT=${2:?outdir}; shift 2
EXTRA=("$@")
REF=/home/user/research/esp32-rv32/probe/repl/build/esp-idf/main/ulp_main
IDF=/home/user/research/esp32/esp-idf
CC=/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin/riscv32-esp-elf-gcc
mkdir -p "$OUT"
# includes: lifted verbatim from the recorded compile command (order preserved)
INC=( $(python3 - "$REF/compile_commands.json" <<'EOF'
import json,shlex,sys
d=json.load(open(sys.argv[1]))
e=[x for x in d if x['file'].endswith('ulp_repl.c')][0]
print(' '.join(t for t in shlex.split(e['command']) if t.startswith('-I')))
EOF
) )
CFLAGS=(-DIS_ULP_COCPU -DULP_RISCV_REGISTER_OPS -Os -march=rv32imc_zicsr_zifencei -mdiv \
        -fdata-sections -ffunction-sections)
CORE=(ulp_riscv_vectors.S start.S ulp_riscv_adc.c ulp_riscv_lock.c ulp_riscv_uart.c \
      ulp_riscv_print.c ulp_riscv_i2c.c ulp_riscv_utils.c ulp_riscv_touch.c \
      ulp_riscv_gpio.c ulp_riscv_interrupt.c)
OBJS=()
nice -n 15 "$CC" "${CFLAGS[@]}" "${EXTRA[@]}" "${INC[@]}" -o "$OUT/ulp_repl.o" -c "$SRC/ulp_repl.c" || exit 1
OBJS+=("$OUT/ulp_repl.o")
for f in "${CORE[@]}"; do
  o="$OUT/$f.o"
  nice -n 15 "$CC" "${CFLAGS[@]}" "${INC[@]}" -o "$o" -c "$IDF/components/ulp/ulp_riscv/ulp_core/$f" || exit 1
  OBJS+=("$o")
done
nice -n 15 "$CC" -march=rv32imc_zicsr_zifencei --specs=nano.specs --specs=nosys.specs -nostartfiles \
  -Wl,--gc-sections -Wl,--no-warn-rwx-segments -Wl,-Map="$OUT/ulp_main.map" \
  -T "$REF/ulp_riscv.ld" "$IDF/components/ulp/ld/esp32s3.peripherals.ld" \
  -o "$OUT/ulp_main.elf" "${OBJS[@]}" || exit 1
# GUARDRAIL: never resolve the size tool via PATH — export.sh was not sourced in this shell, so
# `riscv32-esp-elf-size` expanded empty and the script printed a tidy "total = 0" that looked like a
# real measurement. Derive every tool from the one CC path we pinned from compile_commands.json.
SZ="${CC%gcc}size"
"$SZ" -A "$OUT/ulp_main.elf" | awk '
  $1==".text"||$1==".rodata"||$1==".data"||$1==".bss"{t[$1]=$2}
  END{
    txt=t[".text"]+t[".rodata"];
    printf "text(%s)+rodata(%s) = %d\ndata = %d\nbss  = %d\ntotal = %d\n",
      t[".text"],t[".rodata"],txt,t[".data"],t[".bss"],txt+t[".data"]+t[".bss"]
  }'
