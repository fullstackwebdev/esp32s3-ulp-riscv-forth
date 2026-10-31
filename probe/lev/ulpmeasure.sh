#!/usr/bin/env bash
# ulpmeasure.sh — measure a ULP Forth source tree against the RTC pool, in ~3 seconds.
#
# Recompiles ONLY the candidate source and relinks against the prebuilt IDF ULP core objects
# (vectors, start, ulp_riscv_*). A full `idf.py build` is minutes and needs a CMake tree per
# candidate; the pool total only depends on this link, so this is the whole measurement.
#
#   ./ulpmeasure.sh <src-dir-with-ulp_repl.c> <out.elf>
#
# Prints: .text .rodata .data .bss, the pool total (7856 B limit), and spare.
#
# GUARDRAIL: reuse the IDF core objects instead of rebuilding them, but never reuse the *candidate*
# object — a stale .obj silently reports the previous candidate's size, which is how a "measurement"
# ends up describing a different program than the source in front of you.
set -euo pipefail

SRC=${1:?usage: ulpmeasure.sh <src-dir> <out.elf>}
OUT=${2:?usage: ulpmeasure.sh <src-dir> <out.elf>}
BASE=/home/user/research/esp32-rv32/probe/repl/build/esp-idf/main/ulp_main
OBJ="$SRC/.measure.obj"
# The pool limit is RTC RAM (8 176 B) minus the C-stack reserve. The reserve is a measured figure
# (P21: 244 B worst case; 320 B used by default), and the experimental tree lowers it to 276 — so the
# limit must be settable, or a legal experimental build reports as overflow.
POOL=${POOL:-7856}

export IDF_PATH=/home/user/research/esp32/esp-idf
# shellcheck disable=SC1091
. "$IDF_PATH/export.sh" >/dev/null 2>&1

INCS=$(python3 - "$BASE/compile_commands.json" <<'PY'
import json, shlex, sys
cc = json.load(open(sys.argv[1]))
e = [x for x in cc if x["file"].endswith("src/ulp_repl.c")][0]
cmd = shlex.split(e["command"])
print(" ".join(a for a in cmd if a.startswith("-I") or a in ("-DIS_ULP_COCPU", "-DULP_RISCV_REGISTER_OPS")))
PY
)

# Any assembly in the candidate tree is part of the image: compile each .S and link it in.
# GUARDRAIL: without this a tree whose logic lives in .S silently measures as if that file did not exist —
# the image links, the number looks plausible, and it describes a different program than the source.
ASMOBJS=""
HAVE_ASM=0
for s in "$SRC"/*.S; do
    [ -e "$s" ] || continue
    o="${s%.S}.meas.o"
    nice -n 15 riscv32-esp-elf-gcc -Os -march=rv32imc_zicsr_zifencei -mdiv \
        -ffunction-sections -fdata-sections -c "$s" -o "$o"
    ASMOBJS="$ASMOBJS $o"
    HAVE_ASM=1
done


rm -f "$OBJ"
# shellcheck disable=SC2086
nice -n 15 riscv32-esp-elf-gcc $INCS -Os -march=rv32imc_zicsr_zifencei -mdiv \
    -fdata-sections -ffunction-sections -c "$SRC/ulp_repl.c" -o "$OBJ"

CORE=$(ls "$BASE"/CMakeFiles/ulp_main.dir/home/user/research/esp32/esp-idf/components/ulp/ulp_riscv/ulp_core/*.obj)

# shellcheck disable=SC2086
nice -n 15 riscv32-esp-elf-gcc -march=rv32imc_zicsr_zifencei --specs=nano.specs --specs=nosys.specs \
    -nostartfiles -Wl,--gc-sections -Wl,--no-warn-rwx-segments \
    -T "$BASE/ulp_riscv.ld" \
    /home/user/research/esp32/esp-idf/components/ulp/ld/esp32s3.peripherals.ld \
    "$OBJ" $ASMOBJS $CORE -o "$OUT"

python3 - "$OUT" "$POOL" <<'PY'
import subprocess, sys
elf, pool = sys.argv[1], int(sys.argv[2])
s = subprocess.run(["riscv32-esp-elf-size", "-A", elf], capture_output=True, text=True).stdout
sec = {}
for line in s.splitlines()[2:]:
    f = line.split()
    if len(f) >= 2 and f[0].startswith("."):
        sec[f[0]] = int(f[1])
text = sum(v for k, v in sec.items() if k.startswith(".text"))
ro   = sum(v for k, v in sec.items() if k.startswith(".rodata"))
data = sum(v for k, v in sec.items() if k.startswith(".data"))
bss  = sum(v for k, v in sec.items() if k.startswith(".bss"))
tot  = text + ro + data + bss
print("text=%-6d rodata=%-5d data=%-6d bss=%-6d pool=%-6d spare=%-5d %s"
      % (text, ro, data, bss, tot, pool - tot, "FITS" if tot <= pool else "OVERFLOW"))
PY
rm -f "$OBJ"
