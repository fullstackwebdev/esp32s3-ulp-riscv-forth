#!/bin/bash
# GUARDRAIL (build): the pool number is only comparable if the compile AND link flags are the ones the
# IDF build actually used, so they are copied verbatim from compile_commands.json / build.ninja instead
# of being retyped from memory (a missing -fdata-sections or -Os silently shifts .text by hundreds of B).
# Usage: ./mkpool.sh <outdir> <src-ulp_repl.c> [extra -D...]
#   srcs are compiled into <outdir>, linked with the reference ulp_riscv.ld + esp32s3.peripherals.ld,
#   then text/rodata/data/bss/bin/pool are printed. Nothing outside <outdir> is written.
set -u
OUT=${1:?outdir}
SRC=${2:?src}
shift 2
EXTRA="$*"

TOOL=/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin
IDF=/home/user/research/esp32/esp-idf
# read-only reference build dir (flags, linker script, generated sdkconfig.h)
REF=/home/user/research/esp32-rv32/probe/repl/build/esp-idf/main/ulp_main
CFGCFG=/home/user/research/esp32-rv32/probe/repl/build/config

DEFINES="-DIS_ULP_COCPU -DULP_RISCV_REGISTER_OPS"
FLAGS="-Os -march=rv32imc_zicsr_zifencei -mdiv -fdata-sections -ffunction-sections"

# GUARDRAIL: the include list must stay byte-identical to build.ninja's INCLUDES (see mkpool_flags.sh);
# the IDF ULP core sources need it even though uforth.c only uses <stdint.h>.
INCLUDES=$(cat "$(dirname "$0")/mkpool_includes.txt")

mkdir -p "$OUT" || exit 1
OBJS=""

cc1() { # <src> <obj>
  nice -n 15 timeout 300 "$TOOL/riscv32-esp-elf-gcc" $DEFINES $EXTRA $FLAGS $INCLUDES \
      -o "$2" -c "$1" || { echo "COMPILE FAILED: $1"; exit 1; }
}

cc1 "$SRC" "$OUT/ulp_repl.o"
OBJS="$OUT/ulp_repl.o"

for s in ulp_riscv_vectors.S start.S ulp_riscv_adc.c ulp_riscv_lock.c ulp_riscv_uart.c \
         ulp_riscv_print.c ulp_riscv_i2c.c ulp_riscv_utils.c ulp_riscv_touch.c \
         ulp_riscv_gpio.c ulp_riscv_interrupt.c; do
  o="$OUT/$(echo "$s" | tr . _).o"
  cc1 "$IDF/components/ulp/ulp_riscv/ulp_core/$s" "$o"
  OBJS="$OBJS $o"
done

cp "$REF/ulp_riscv.ld" "$OUT/ulp_riscv.ld" || exit 1

nice -n 15 timeout 300 "$TOOL/riscv32-esp-elf-gcc" \
  -march=rv32imc_zicsr_zifencei --specs=nano.specs --specs=nosys.specs -nostartfiles \
  -Wl,--gc-sections -Wl,--no-warn-rwx-segments -Wl,-Map="$OUT/ulp_main.map" \
  -T "$OUT/ulp_riscv.ld" "$IDF/components/ulp/ld/esp32s3.peripherals.ld" \
  $OBJS -o "$OUT/ulp_main.elf" || { echo "LINK FAILED"; exit 1; }

"$TOOL/riscv32-esp-elf-objcopy" -O binary "$OUT/ulp_main.elf" "$OUT/ulp_main.bin"
"$TOOL/riscv32-esp-elf-nm" -f posix -g "$OUT/ulp_main.elf" > "$OUT/ulp_main.sym"
"$TOOL/riscv32-esp-elf-size" "$OUT/ulp_main.elf"

# GUARDRAIL: parse the map with python, not awk — Ubuntu's mawk has no strtonum(), so "0x119c"+0 is 0
# and the pool total silently printed as 0 (measured here). Hex must be int(x,16).
python3 - "$OUT/ulp_main.map" <<'PY'
import sys, re
want = {'.text': 'text', '.rodata': 'rodata', '.data': 'data', '.bss': 'bss'}
s = {}
for line in open(sys.argv[1]):
    p = line.split()
    if len(p) >= 3 and p[0] in want:
        s.setdefault(want[p[0]], int(p[2], 16))
t = s.get('text',0); r = s.get('rodata',0); d = s.get('data',0); b = s.get('bss',0)
print("text=%d rodata=%d data=%d bss=%d pool=%d bin=%d" % (t, r, d, b, t+r+d+b, t+r+d))
PY
ls -l "$OUT/ulp_main.bin" | awk '{print "bin_bytes(on_disk)=" $5}'
