#!/bin/bash
# fast size loop: rebuild only the ULP TU with IDF's own flags and report section sizes
set -e
cd "$(dirname "$0")/.."
export IDF_PATH=/home/user/research/esp32/esp-idf
CCDIR=build/esp-idf/main/ulp_main
python3 - <<'PY' > artifacts/cc_cmd.txt
import json,shlex
cc=json.load(open('build/esp-idf/main/ulp_main/compile_commands.json'))
e=[x for x in cc if x['file'].endswith('ulp_p39.c')][0]
a=shlex.split(e['command'])
a[a.index('-o')+1]='artifacts/ulp_p39.o'
a=[x for x in a]
print(' '.join(shlex.quote(x) for x in a))
PY
eval "$(cat artifacts/cc_cmd.txt)"
/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin/riscv32-esp-elf-size -A artifacts/ulp_p39.o \
  | awk 'NR>2 && $1 ~ /^\.(text|rodata|data|bss|sbss)/ {t[$1]=$2; tot+=$2} END {print "OBJ total(bytes in sections) =",tot}'
/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin/riscv32-esp-elf-size -A artifacts/ulp_p39.o \
  | awk 'NR>2 && $1 ~ /^\.text/ {print $2, $1}' | sort -rn | head -6
