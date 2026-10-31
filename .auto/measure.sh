#!/usr/bin/env bash
# .auto/measure.sh — the autoresearch metric: APPLICATION SPACE in bytes.
#
# Why it is computed, not read: app space = MEMSZ - BLKSZ - headers - code, and MEMSZ is bounded by the
# pool. So a byte saved in .text/.rodata/.bss becomes exactly one byte of MEMSZ, i.e. one byte of app
# space. This script (1) twin-builds src/ with the shipping flags, (2) computes the largest MEMSZ the pool
# allows, (3) bakes at that MEMSZ *into .auto/tmp* and reports the bake's own "free" number.
#
# GUARDRAIL: the bake here writes to .auto/tmp, never src/image.h. The tree's image.h is only replaced on a
# `keep`, together with MEMSZ — a measurement must not mutate the thing it measures (P42).
# GUARDRAIL: do not parse ulp_repl.c for the flag set (R6). BAKEFLAGS below must track it, and the bake
# prints the word count so a drift shows up as a different word count, not as a silent wrong number.
set -euo pipefail
cd "$(dirname "$0")/.."

POOL=7856          # the flash guard's limit (flash_safe.sh)
SPARE=3            # keep the same 3 B of headroom the shipping image has
# GUARDRAIL: MEMSZ is derived from the built artifact (`data = MEMSZ + 16`), not from a constant and not by
# parsing ulp_repl.c (R6). It used to be hardcoded 1688, so the first keep — which moved MEMSZ to 1696 —
# made the metric measure at the OLD value and report 727 for a tree that had 735. A metric that lags the
# tree is worse than a slow one.
TMP=.auto/tmp; mkdir -p "$TMP"
RVV_BIN=/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin
BAKEFLAGS="-O2 -fno-strict-aliasing -DHOST -DP43_TASKS -DP33_BLOCK -DBLKPRIM -DBLKSZ=128 -DBLK_MB=4 -DTIBSZ=128 -DP33_NOPAGE -DP30_HANDCOPY -DP54_BINOPS=10"

# 1. twin build (fast). Fails loudly if the twin cannot be produced.
OUT=$PWD/.auto/tmp/twin timeout 300 probe/repl/tools/measure.sh auto >"$TMP/twin.log" 2>&1 || { echo "TWIN BUILD FAILED"; tail -20 "$TMP/twin.log"; exit 1; }
ELF=.auto/tmp/twin/auto.elf
[ -f "$ELF" ] || { echo "TWIN ELF MISSING: $ELF"; exit 1; }

# 2. sections, straight from the artifact
read -r TEXT RODATA SRODATA DATA BSS TOTAL <<<"$("$RVV_BIN/riscv32-esp-elf-size" -A "$ELF" | awk '
  /^\.text/{t+=$2} /^\.rodata/{r+=$2} /^\.srodata/{sr+=$2} /^\.data/{d+=$2} /^\.bss/{b+=$2}
  END{print t+0, r+0, sr+0, d+0, b+0, t+r+sr+d+b}')"

MEMSZ_NOW=$(( DATA - 16 ))
HEADROOM=$(( POOL - TOTAL - SPARE ))
M=$(( MEMSZ_NOW + HEADROOM ))
# GUARDRAIL: the TWIN is optimistic and by a variable amount — measured at 18 B after the seven -fno-tree-*
# flags went in (the twin linked 5 657 B of non-data, the shipping build 5 675 B), so the twin's ceiling of
# 2 180 did not fit the real image (pool 7 871 > 7 856) and the flash guard refused it. A metric that
# reports a ceiling the shipping image cannot reach is a lie in the direction that hurts: it says "keep".
# GUARDRAIL: so cross-check against the REAL shipping ELF, which is also the artifact that gets flashed, and
# take the SMALLER ceiling. It requires a real build after source changes — which is already true for
# compile_commands.json (see the note at the top).
REAL=probe/repl/build/esp-idf/main/ulp_main/ulp_main.elf
if [ -f "$REAL" ]; then
  read -r RT RR RS RD RB <<<"$("$RVV_BIN/riscv32-esp-elf-size" -A "$REAL" | awk '
    /^\.text/{t+=$2} /^\.rodata/{r+=$2} /^\.srodata/{sr+=$2} /^\.data/{d+=$2} /^\.bss/{b+=$2}
    END{print t+0, r+0, sr+0, d+0, b+0}')"
  RTOTAL=$(( RT + RR + RS + RB ))
  MREAL=$(( POOL - SPARE - RTOTAL - 16 ))
  if [ "$MREAL" -lt "$M" ]; then
    echo "note: twin ceiling $M reduced to $MREAL by the real build (twin is optimistic)" >&2
    M=$MREAL
  fi
fi

# 3. bake at M to learn headers/code/free (the dictionary side of app space)
gcc $BAKEFLAGS -DMEMSZ=$M -o "$TMP/bake" probe/repl/src/uforth.c
BAKE=$("$TMP/bake" -d "$TMP/image.h" probe/repl/src/p39_prelude.fs probe/repl/src/line.fs 2>&1 | sed -nE 's/.*free ([0-9]+).*/\1/p' || true)
[ -n "$BAKE" ] || { echo "BAKE PRODUCED NO parseable free count"; exit 1; }
WORDS=$("$TMP/bake" -d "$TMP/image.h" probe/repl/src/p39_prelude.fs probe/repl/src/line.fs 2>&1 | sed -nE 's/.* ([0-9]+) words.*/\1/p' | tail -1)

echo "METRIC app_bytes=$BAKE"
echo "METRIC text=$TEXT"
echo "METRIC rodata=$((RODATA + SRODATA))"
echo "METRIC bss=$BSS"
echo "METRIC pool=$TOTAL"
echo "METRIC memsz_max=$M"
echo "METRIC words=${WORDS:-0}"
echo "sections: text=$TEXT rodata=$RODATA srodata=$SRODATA data=$DATA bss=$BSS total=$TOTAL headroom=$HEADROOM memsz_max=$M free=$BAKE words=${WORDS:-?}"
