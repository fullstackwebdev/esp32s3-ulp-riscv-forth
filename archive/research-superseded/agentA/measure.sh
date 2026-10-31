#!/usr/bin/env bash
# measure.sh — price one ULP-engine variant in bytes, with the shipping flags and the shipping link line.
#
#   ./measure.sh <variant-name> [extra cflags ...]
#
# Method is tools/disasm.sh's, adapted (same compile command from ulp_main/compile_commands.json, same
# link line from ulp_main/build.ninja, same object list minus our own), so the number is the number the
# real ULP binary would have. `base` is re-measured every run and its .text sha256 is compared with the
# shipping ELF: if the twin does not reproduce the flashed .text, no variant number below it is valid.
#
# GUARDRAIL: the ULP sub-build takes its flags from IDF's toolchain file, so a C flag typed on a
# command line is only a hypothesis until the twin proves it links to the SAME .text as the ship
# image — that check is the whole value of this script.
# GUARDRAIL: never write into probe/repl/build (a shipping artifact that no longer matches what was
# flashed is worse than no artifact); everything here lands in agentA/out/.
set -euo pipefail
cd "$(dirname "$0")"

REPL=/home/user/research/esp32-rv32/probe/repl
UB=$REPL/build/esp-idf/main/ulp_main
RVV=/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin/riscv32-esp-elf-gcc
OUT=out
mkdir -p "$OUT"

NAME=${1:?variant name}
shift || true

python3 - "$UB" "$RVV" "$NAME" "$PWD" "$@" <<'PY'
import json, os, re, subprocess, sys, pathlib, shlex
ub, gcc, name, root = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3], pathlib.Path(sys.argv[4])
extra = sys.argv[5:]
out = root / "out"
cc = json.load(open(ub / "compile_commands.json"))
e = next(x for x in cc if x["file"].endswith("/src/ulp_repl.c"))
src = (root / "src" / "ulp_repl.c")
cmd = e["command"]
# same compile, our source, our object
cmd = re.sub(r"-o\s+\S+", f"-o {out}/{name}.o", cmd, count=1)
cmd = cmd.replace("/home/user/research/esp32-rv32/probe/repl/src/ulp_repl.c", str(src))
cmd = cmd.replace(
    "/home/user/research/esp32-rv32/probe/repl/build/config",
    "/home/user/research/esp32-rv32/probe/repl/build/config")
if extra:
    cmd = cmd.replace("-Os ", "-Os " + " ".join(extra) + " ", 1)
try:
    subprocess.run(shlex.split(cmd), check=True, cwd=e["directory"])
except subprocess.CalledProcessError:
    sys.exit(f"measure: compile of {name} failed (see the compiler output above)")

# LINK_EXTRA lets a lever that only acts at link time (-mrelax) be priced too; without it the compile
# flag records a R_RISCV_RELAX that the linker never applies and the row would read as a zero.
link_extra = os.environ.get("LINK_EXTRA", "").split()
link_flags = ("-march=rv32imc_zicsr_zifencei --specs=nano.specs --specs=nosys.specs -nostartfiles "
              "-Wl,--gc-sections -Wl,--no-warn-rwx-segments "
              f"-Wl,-Map={out}/{name}.map -T {ub}/ulp_riscv.ld "
              "/home/user/research/esp32/esp-idf/components/ulp/ld/esp32s3.peripherals.ld")
line = (ub / "build.ninja").read_text().split("build ulp_main.elf:")[1].split("\n")[0]
objs = [str(ub / o) for o in re.findall(r'(CMakeFiles/ulp_main\.dir/\S+?\.obj)', line)]
objs = [o for o in objs if not o.endswith("ulp_repl.c.obj")]
try:
    subprocess.run([gcc] + link_extra + link_flags.split() + [f"{out}/{name}.o"] + objs
                   + ["-o", f"{out}/{name}.elf"], check=True)
except subprocess.CalledProcessError:
    sys.exit(f"measure: link of {name} failed")
print(f"built out/{name}.elf")
PY

SZ=/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin/riscv32-esp-elf-size
OBJCOPY=/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin/riscv32-esp-elf-objcopy

elf=$OUT/$NAME.elf
# .text and .rodata separately: `size` folds .rodata into its "text" column, and the jump table lives in
# .rodata, so the two numbers have to be read apart or TASK 1's answer is invisible.
# GUARDRAIL: use command substitution, not `read < <(awk ...)` — awk's printf emits no trailing newline, so
# `read` returns 1 at EOF and `set -e` kills the script *after* a successful build, printing nothing. If a
# measurement script ever exits quietly, check the read before believing the numbers.
vals=$("$SZ" -A "$elf" | awk '/^\.text |^\.rodata |^\.data |^\.bss /{printf "%s ", $2}')
tt=${vals%% *}; vals=${vals#* }; tr=${vals%% *}; vals=${vals#* }
td=${vals%% *}; tb=${vals#* }
# the object carries -ffunction-sections sections (.text.vm_enter, ...), so a plain `.text` row reads 0 —
# sum the family, or the column silently claims the object is empty.
ot=$("$SZ" -A "$OUT/$NAME.o" | awk '/^\.text\./{t+=$2} END{print (t+0)}')
orod=$("$SZ" -A "$OUT/$NAME.o" | awk '/^\.rodata/{t+=$2} END{print (t+0)}')
"$OBJCOPY" -O binary --only-section=.text "$elf" "$OUT/$NAME.text"
h=$(sha256sum "$OUT/$NAME.text" | cut -c1-16)
printf '%-22s elf .text=%-5s .rodata=%-5s .data=%-5s .bss=%-5s | obj .text=%-5s .rodata=%-5s | sha=%s\n' \
       "$NAME" "$tt" "$tr" "$td" "$tb" "$ot" "$orod" "$h"
