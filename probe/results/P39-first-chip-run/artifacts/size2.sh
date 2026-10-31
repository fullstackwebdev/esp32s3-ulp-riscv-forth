#!/bin/bash
# P39 sizes: the real ULP object and the control object (hooks + main, no engine), same flags.
set -e
cd "$(dirname "$0")/.."
python3 - <<'PY' > artifacts/build_two.sh
import json, shlex
cc = json.load(open('build/esp-idf/main/ulp_main/compile_commands.json'))
e = [x for x in cc if x['file'].endswith('ulp_p39.c')][0]
a = shlex.split(e['command'])
def emit(out, extra):
    b = list(a)
    b[b.index('-o') + 1] = out
    print(' '.join(shlex.quote(x) for x in b + extra))
emit('artifacts/ulp_p39.o', [])
emit('artifacts/ulp_p39_ctl.o', ['-DP39_HARNESS_ONLY'])
PY
bash artifacts/build_two.sh
SZ=/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin/riscv32-esp-elf-size
for n in ulp_p39 ulp_p39_ctl; do
  printf '%-14s ' "$n"
  $SZ -A artifacts/$n.o | awk 'NR>2 && $1 ~ /^\.(text|rodata|data|bss|sbss)/ {t+=$2; if ($1 ~ /^\.text/ && $1==".text.rodata") r=$2} END {print "sections total =",t,"B"}'
done
