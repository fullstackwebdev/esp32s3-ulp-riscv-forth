#!/usr/bin/env bash
# GUARDRAIL: promoted from probe/research/P54-fail/measure.sh to be the ONE twin-build harness — the
# research copies are archives now, and a second copy is how the shipped image came to be measured two
# ways. It is the fast path of the autoresearch loop: compile probe/repl/src with the SHIPPING flags and
# link line, ~2 s, instead of a 90 s idf.py build.
# GUARDRAIL: the baseline still has to be checked against the flashed ELF before trusting a delta — but
# only while src/ is unmodified. Once the loop changes a source file the twin legitimately differs from
# the stale build/ tree, so measure.sh reports the sha and the caller decides; do not gate a metric on it.
# measure.sh — price one ULP-engine variant in bytes, with the shipping flags and the shipping link line.
#
#   ./measure.sh <variant-name> [extra cflags ...]
#   SRCDIR=variants/var_a ./measure.sh var_a    # price a copy of src/ instead of src/
#
# GUARDRAIL: a variant must be a SEPARATE copy of src/, never an in-place edit of the baseline: with
# one tree, the next row is measured against a baseline that no longer exists and the first row's
# sha256 proof silently becomes a claim about different source. SRCDIR exists for that.
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
# the FLASHED ULP image, i.e. the artifact every delta is a delta FROM
SHIP=$UB/ulp_main.elf
RVV=/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin/riscv32-esp-elf-gcc
# GUARDRAIL: `OUT=out` unconditionally overrode the caller's value, so the autoresearch loop's twin
# ELFs landed in the shipping tree while the caller looked for them in .auto/tmp. Respect an
# inherited OUT; default to out/ for interactive use.
OUT=${OUT:-out}
mkdir -p "$OUT"

NAME=${1:?variant name}
shift || true

# GUARDRAIL: SRCDIR defaults to the SHIPPING tree. This script used to live in a research dir with its own
# src/ beside it, where the default "src/" worked; promoted to probe/repl/tools the same default resolved
# against the caller's cwd and the twin build died on a missing file. The tool's job is to price the tree
# that ships unless a variant is named explicitly.
export SRCDIR=${SRCDIR:-$REPL/src}

python3 - "$UB" "$RVV" "$NAME" "$PWD" "$@" <<'PY'
import json, os, re, subprocess, sys, pathlib, shlex
ub, gcc, name, root = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3], pathlib.Path(sys.argv[4])
extra = sys.argv[5:]
# GUARDRAIL: OUT is overridable so a caller (the autoresearch loop) can keep twin ELFs out of the
# shipping tree. The directory is created here, so a later missing ELF is a real failure and not a
# "the tool wrote it somewhere else" mystery.
out = pathlib.Path(os.environ.get("OUT", str(root / "out"))).resolve()
out.mkdir(parents=True, exist_ok=True)
cc = json.load(open(ub / "compile_commands.json"))
e = next(x for x in cc if x["file"].endswith("/src/ulp_repl.c"))
# GUARDRAIL: resolve SRCDIR to an absolute path — the compile runs with cwd = the directory IDF recorded,
# so a relative variant path silently compiles "nothing there" (cc1: No such file) and the row is lost.
src = pathlib.Path(os.environ.get("SRCDIR", str(root / "src"))).resolve() / "ulp_repl.c"
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
# GUARDRAIL: .text/.rodata/.data/.bss is NOT the whole image. GCC puts a small const array in its OWN
# section (.srodata.CSWTCH.NNN, from -fdata-sections), and the linker places it between .rodata and
# .data — so a variant that swaps a .text jump table for a .rodata byte table can look 24 B lighter
# while 6 B of it simply moved to a section this row never printed. The pool is the END OF THE LAST
# PLACED SECTION; quote `span`, not the four named rows, or the delta is a measurement artifact.
# GUARDRAIL: `size -A` prints exactly THREE fields per row (name, size, addr), debug sections sit at
# addr 0 and must not be counted — an NF>=4 test here matched nothing and printed span=0, which reads
# like "this variant frees the whole image" instead of "the awk is wrong".
span=$("$SZ" -A "$elf" | awk 'NF==3 && $2 ~ /^[0-9]+$/ && $3 ~ /^[0-9]+$/ && $3 != 0 {e=$3+$2; if (e>m) m=e} END{print m+0}')
# the object carries -ffunction-sections sections (.text.vm_enter, ...), so a plain `.text` row reads 0 —
# sum the family, or the column silently claims the object is empty.
ot=$("$SZ" -A "$OUT/$NAME.o" | awk '/^\.text\./{t+=$2} END{print (t+0)}')
orod=$("$SZ" -A "$OUT/$NAME.o" | awk '/^\.rodata/{t+=$2} END{print (t+0)}')
"$OBJCOPY" -O binary --only-section=.text "$elf" "$OUT/$NAME.text"
h=$(sha256sum "$OUT/$NAME.text" | cut -c1-16)
# GUARDRAIL: "is the twin the shipped machine?" used to be an operator step (read the sha in two files,
# compare by eye) and a busy run skips it — then every delta below is a delta from a build nobody flashed.
# The baseline row now REFUSES to print a pool span unless its .text sha256 equals the shipped ELF's.
# GUARDRAIL: only the baseline is asserted. A variant is EXPECTED to differ, so asserting here for every
# name would either fail every real row or get `|| true`'d, which is the same as not having the check.
if [ "$NAME" = base ]; then
  [ -f "$SHIP" ] || { echo "measure: no shipping ELF at $SHIP — cannot certify the baseline twin" >&2; exit 1; }
  "$OBJCOPY" -O binary --only-section=.text "$SHIP" "$OUT/ship.text"
  sh=$(sha256sum "$OUT/ship.text" | cut -c1-16)
  if [ "$h" != "$sh" ]; then
    echo "measure: BASELINE MISMATCH — twin .text sha=$h, shipped .text sha=$sh" >&2
    echo "measure: no delta from this twin is a measurement. Fix the compile line before quoting one." >&2
    exit 1
  fi
  printf '%-22s baseline twin .text == shipped .text (sha=%s)\n' "$NAME" "$sh"
fi
printf '%-22s elf .text=%-5s .rodata=%-5s .data=%-5s .bss=%-5s | obj .text=%-5s .rodata=%-5s | sha=%s\n' \
       "$NAME" "$tt" "$tr" "$td" "$tb" "$ot" "$orod" "$h"
printf '%-22s pool span=%s B (end of last placed section; THIS is the bytes-of-app-space number)\n' \
       "$NAME" "$span"
