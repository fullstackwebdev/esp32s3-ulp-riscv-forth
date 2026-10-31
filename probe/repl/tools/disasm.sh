#!/usr/bin/env bash
# disasm.sh — produce disassembly for BOTH cores into probe-results/asm/, including a
# source-interleaved (-S) listing for the ULP.
#
#   ./tools/disasm.sh              # plain + source-interleaved, symbols, both cores
#
# GUARDRAIL: the ULP is built WITHOUT -g, so `objdump -S` on the shipping ELF silently produces a listing
# with no source in it — which reads like "the tool did not work" rather than "there is no debug info".
# So this script builds a -g TWIN of ulp_repl.c into asm_dbg/ using the exact command IDF recorded in
# ulp_main/compile_commands.json plus the exact link line from ulp_main/CMakeFiles/rules.ninja. It then
# proves the twin is the same machine by comparing sha256 of the .text of both ELFs, and REFUSES to emit
# the interleaved file if they differ. Without that check the listing would be of a build nobody measured.
#
# GUARDRAIL: never edit build/ in place to add -g. A shipping artifact that no longer matches what was
# flashed is worse than no disassembly; the twin lives outside the build tree.
set -euo pipefail
cd "$(dirname "$0")/.."
export IDF_PATH=/home/user/research/esp32/esp-idf
# shellcheck disable=SC1091
. "$IDF_PATH/export.sh" >/dev/null 2>&1

RVV=/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin/riscv32-esp-elf-gcc
OUT=probe-results/asm
UB=build/esp-idf/main/ulp_main
ULP_ELF=$UB/ulp_main.elf
APP_ELF=$(ls build/*.elf | grep -v ulp | head -1)
mkdir -p "$OUT" asm_dbg

[ -f "$ULP_ELF" ] || { echo "disasm: no ULP ELF — run idf.py build" >&2; exit 2; }

# ---- plain listings and symbols -------------------------------------------------
riscv32-esp-elf-objdump -d "$ULP_ELF"            > "$OUT/ulp_main.dis"
riscv32-esp-elf-nm -S --size-sort "$ULP_ELF"     > "$OUT/ulp_main.syms"
xtensa-esp32s3-elf-objdump -d "$APP_ELF"         > "$OUT/esp32s3_app.dis"
xtensa-esp32s3-elf-nm -S --size-sort "$APP_ELF"  > "$OUT/esp32s3_app.syms"

# ---- ULP debug twin -------------------------------------------------------------
python3 - "$UB" "$RVV" <<'PY'
import json, re, subprocess, sys, pathlib, shlex
ub, gcc = pathlib.Path(sys.argv[1]).resolve(), sys.argv[2]
out = pathlib.Path("asm_dbg").resolve()
cc = json.load(open(ub/"compile_commands.json"))
e = next(x for x in cc if x["file"].endswith("/src/ulp_repl.c"))
cmd = re.sub(r"-o\s+\S+", f"-o {out}/ulp_repl.o", e["command"], count=1).replace("-Os", "-Os -g", 1)
subprocess.run(shlex.split(cmd), check=True, cwd=e["directory"])
flags = "-Os -march=rv32imc_zicsr_zifencei -mdiv -fdata-sections -ffunction-sections"
link_flags = ("-march=rv32imc_zicsr_zifencei --specs=nano.specs --specs=nosys.specs -nostartfiles "
              "-Wl,--gc-sections -Wl,--no-warn-rwx-segments "
              f"-Wl,-Map={out}/ulp_main_dbg.map -T {ub}/ulp_riscv.ld "
              "/home/user/research/esp32/esp-idf/components/ulp/ld/esp32s3.peripherals.ld")
line = (ub/"build.ninja").read_text().split("build ulp_main.elf:")[1].split("\n")[0]
objs = [str(ub/o) for o in re.findall(r'(CMakeFiles/ulp_main\.dir/\S+?\.obj)', line)]
objs = [o for o in objs if not o.endswith("ulp_repl.c.obj")]
subprocess.run([gcc, "-g"] + flags.split() + link_flags.split() + [f"{out}/ulp_repl.o"] + objs
               + ["-o", f"{out}/ulp_main_dbg.elf"], check=True)
print("twin built", out/"ulp_main_dbg.elf")
PY

# ---- prove the twin is the same machine, then emit the interleaved listing -----
riscv32-esp-elf-objcopy -O binary --only-section=.text "$ULP_ELF" asm_dbg/ship.text
riscv32-esp-elf-objcopy -O binary --only-section=.text asm_dbg/ulp_main_dbg.elf asm_dbg/dbg.text
if ! cmp -s asm_dbg/ship.text asm_dbg/dbg.text; then
    echo "disasm: REFUSING — -g changed the code, so the interleaved listing is not the shipping build" >&2
    sha256sum asm_dbg/ship.text asm_dbg/dbg.text >&2
    exit 3
fi
echo "disasm: .text identical (sha256 $(sha256sum asm_dbg/ship.text | cut -c1-16)…) — interleaving is valid"
riscv32-esp-elf-objdump -d -S -l asm_dbg/ulp_main_dbg.elf > "$OUT/ulp_main-src.dis"
xtensa-esp32s3-elf-objdump -d -S -l "$APP_ELF"          > "$OUT/esp32s3_app-src.dis"

wc -l "$OUT"/*.dis | sed "s|$OUT/||"
