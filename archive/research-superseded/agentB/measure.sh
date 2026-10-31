#!/usr/bin/env bash
# measure.sh <srcdir> <tag> — twin-build ONE ulp_repl.c into agentB/out/<tag>/ and print its section sizes.
#
# GUARDRAIL: do NOT edit probe/repl/src or build/ in place — the shipping ELF must keep matching what is
# flashed. This builds a twin from a private copy of src/ using the exact per-file command IDF recorded
# (cc.txt, taken from ulp_main/compile_commands.json) and the exact link line from ulp_main/build.ninja,
# swapping ONLY the ulp_repl.c object. Same compiler, same flags, same other objects -> the size delta is
# the edit's delta and nothing else's (R9: validate the harness before trusting the number).
#
# GUARDRAIL: --gc-sections changes the answer, so the twin must be linked by the SAME link line, not by a
# hand-written one. uforth.c is #included into ulp_repl.c, so every string that `say()` uses from uforth.c
# is decided at link time: an unused function's .rodata disappears, and a hand-written link line would
# silently keep (or drop) a different set of strings than the shipping build does.
set -euo pipefail
cd "$(dirname "$0")"
SRC=$1; TAG=$2
RVBIN=/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin
UB=/home/user/research/esp32-rv32/probe/repl/build/esp-idf/main/ulp_main
OUT=out/$TAG
mkdir -p "$OUT"

# ---- compile: recorded command, source swapped for the copy, -I for the copy added first -----------
mapfile -t CC < cc.txt
DIR=${CC[0]}
# GUARDRAIL: rewrite the `-o` FIRST, then the source path. The object path contains the source path as a
# substring (`CMakeFiles/ulp_main.dir/home/.../src/ulp_repl.c.obj`), so a source-path sed done first hits
# the OBJECT name and leaves the real `-c` argument alone — the build then silently recompiles the
# SHIPPING source and reports a delta of exactly 0 B for an edit that is not in the measurement.
# The grep below is the check that this did not happen (R9: a harness that measures the wrong program
# returns a perfectly plausible number).
NEWCMD=$(printf '%s' "${CC[1]}" | python3 -c '
import re, sys
cmd = sys.stdin.read()
out, src = sys.argv[1], sys.argv[2]
old = "/home/user/research/esp32-rv32/probe/repl/src/ulp_repl.c"
cmd = re.sub(r"-o\s+\S+", f"-o {out}/ulp_repl.o", cmd, count=1)
assert old in cmd, "compile command no longer names the shipping source — re-derive cc.txt"
cmd = cmd.replace(old, f"{src}/ulp_repl.c")
cmd = cmd.replace(" -DIS_ULP_COCPU", f" -I{src} -DIS_ULP_COCPU", 1)
print(cmd)' "$PWD/$OUT" "$PWD/$SRC")
case $NEWCMD in
    *"$PWD/$SRC/ulp_repl.c"*) ;;
    *) echo "measure: rewrite did not take — refusing to measure the wrong source" >&2; exit 3 ;;
esac
case $NEWCMD in
    *probe/repl/src/ulp_repl.c*) echo "measure: shipping source still on the command line" >&2; exit 3 ;;
    *) ;;
esac
(cd "$DIR" && nice -n 15 timeout 600 bash -c "$NEWCMD")

# ---- link: recorded link line, ulp_repl object swapped ----------------------------------------------
OBJS=$(sed -n 's/^build ulp_main\.elf: [^ ]* //p' "$UB/build.ninja" | head -1)
# GUARDRAIL: ninja's order-only deps (`|| ld_script`) are NOT inputs — passing them to the linker yields
# "cannot find .../||: No such file" and the twin never links. Truncate at `||` before using the list.
OBJS=${OBJS%%||*}
[ -n "$OBJS" ] || { echo "measure: no link line in build.ninja" >&2; exit 4; }
LINKS=()
for o in $OBJS; do
    case $o in
        */src/ulp_repl.c.obj) LINKS+=("$PWD/$OUT/ulp_repl.o") ;;
        *)                    LINKS+=("$UB/$o") ;;
    esac
done
LN=$(sed -n 's/^  LINK_FLAGS = //p' "$UB/build.ninja" | head -1)
"$RVBIN/riscv32-esp-elf-gcc" -Os -march=rv32imc_zicsr_zifencei -mdiv -fdata-sections \
    -ffunction-sections -msave-restore $LN "${LINKS[@]}" -o "$OUT/ulp_main.elf"

"$RVBIN/riscv32-esp-elf-size" -A "$OUT/ulp_main.elf" | awk -v t="$TAG" '
    $1==".text"{T=$2} $1==".rodata"{R=$2} $1==".data"{D=$2} $1==".bss"{B=$2}
    END{printf "%s text=%d rodata=%d data=%d bss=%d | ulp_bin(text+rodata+data)=%d\n", t, T, R, D, B, T+R+D}'
