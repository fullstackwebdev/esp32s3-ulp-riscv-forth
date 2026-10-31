#!/usr/bin/env bash
# countdown.sh — how many bytes still stand between this build and blocks.
#
# Prints one line. Run it after every change; the number is the only progress metric that matters
# until blocks fit. Positive = still short. Zero or negative = blocks fit in 7 856 B.
#
# The target is a FIXED configuration, so the countdown is comparable across changes:
#   block words as C primitives   BLK_DICT  40 B   (3 primitive headers; the Forth layer costs 456-530,
#                                                  E-059 measured both, and C prims are the cheaper shape)
#   block buffer                  BLKSZ    512 B   (BLKSZ, inside MEMSZ)
#   block plumbing                BLK_CODE 810 B   (blk_xfer 186 + blk_sum 56 + vm_enter growth ~290
#                                                  + blk_say 34 = 566 text, +16 rodata, +228 bss for
#                                                  mailbox[54] and blkvars — E-059, object-section sums)
#   every MEMSZ byte also carries 16 B of non-mem .data, as in the shipping link.
#
# GUARDRAIL: the constants above are measurements, not guesses, and they are the *cheapest* known shape.
# If a cheaper block layer is ever built (256 B blocks, a 16 B mailbox), change these constants and say so
# in the commit — a countdown computed against a stale target is how "620 B of app space" survived for weeks
# (F-06) and how R5 claimed blocks were 968 B when they were 1 300+ (E-059).
set -euo pipefail
cd "$(dirname "$0")"
export IDF_PATH=/home/user/research/esp32/esp-idf
# shellcheck disable=SC1091
. "$IDF_PATH/export.sh" >/dev/null 2>&1 || true

POOL=7856
BLK_DICT=40
BLKSZ=512
BLK_CODE=810
DATA_PAD=16

ELF=build/esp-idf/main/ulp_main/ulp_main.elf
[ -f "$ELF" ] || { echo "countdown: no build (run idf.py build)"; exit 2; }

read -r TEXT RODATA BSS <<<"$(riscv32-esp-elf-size -A "$ELF" | awk '
    /^\.text/   {t+=$2}
    /^\.rodata/ {r+=$2}
    /^\.bss/    {b+=$2}
    END         {print t, r, b}')"

MEMSZ=$(sed -nE 's/^#define MEMSZ +([0-9]+).*/\1/p' src/ulp_repl.c)
# V_HERE is the u32 at offset 4 of the baked image (V_STATE, V_HERE, V_LATEST, V_BASE ...)
# GUARDRAIL: P51 keeps the dictionary's HEADERS in their own area at the top of mem[], growing down from
# MEMSZ (or from the block buffer's base). App space is therefore no longer MEMSZ - V_HERE: that counts the
# header area as free and reports a number the machine cannot use — the same class of error as the "620 B
# of app space" that needed a pool we never had (F-06). App space is V_LATEST - V_HERE.
VLATEST=$(python3 - <<'PYIMG'
import re, struct
raw = re.findall(r"0x([0-9a-f]{2})", open("src/image.h").read())
b = bytes(int(x, 16) for x in raw)
print(struct.unpack_from("<I", b, 8)[0])
PYIMG
)
VHERE=$(python3 - <<'PY'
import re, struct
raw = re.findall(r"0x([0-9a-f]{2})", open("src/image.h").read())
b = bytes(int(x, 16) for x in raw)
print(struct.unpack_from("<I", b, 4)[0])
PY
)

# Optional scenario flags, each one a MEASURED lever (see docs/13-levers.md):
#   -m  mailbox[54] -> 16 B          : BLK_CODE loses 200 B of block-layer bss
#   -b  256 B blocks instead of 512  : the buffer need halves
#   -a N  assembly dispatcher saves N bytes of text
#   -r N  further ring shrink saves N bytes of bss
#   -s N  C-stack reserve trim returns N bytes to the pool
MAILBOX=0; BLK_256=0; ASM=0; RINGS=0; STACK=0
while [ $# -gt 0 ]; do
    case "$1" in
        -m) MAILBOX=1 ;;
        -b) BLK_256=1 ;;
        -a) ASM=$2; shift ;;
        -r) RINGS=$2; shift ;;
        -s) STACK=$2; shift ;;
        --ladder) LADDER=1 ;;
        *) echo "countdown: unknown arg $1" >&2; exit 2 ;;
    esac
    shift
done

if [ "${MAILBOX:-0}" = 1 ]; then BLK_CODE=$((BLK_CODE - 200)); fi
if [ "${BLK_256:-0}" = 1 ]; then BLKSZ=256; fi
# asm/rings/stack all return bytes to the pool, which is the same thing as adding to "have"
FREED=$(( ${ASM:-0} + ${RINGS:-0} + ${STACK:-0} ))

OVERHEAD=$((TEXT + RODATA + BSS - FREED))
TARGET_MEMSZ=$((VHERE + BLK_DICT + BLKSZ))
TARGET_POOL=$((OVERHEAD + BLK_CODE + TARGET_MEMSZ + DATA_PAD))
GAP=$((TARGET_POOL - POOL))
APP=$((VLATEST - VHERE))
POOL_USED=$((OVERHEAD + MEMSZ + DATA_PAD))

if [ "$GAP" -gt 0 ]; then
    verdict="${GAP} B to go"
else
    verdict="FITS, $((-GAP)) B spare"
fi

NEED=$((BLK_DICT + BLKSZ + BLK_CODE))
HAVE=$((APP + POOL - POOL_USED))

printf 'blocks countdown: %-12s [pool %d/%d]\n' "$verdict" "$POOL_USED" "$POOL"
printf '  need: dict %d + buffer %d + block code %d = %d B\n' "$BLK_DICT" "$BLKSZ" "$BLK_CODE" "$NEED"
printf '  have: app %d + pool spare %d = %d B\n' "$APP" "$((POOL - POOL_USED))" "$HAVE"
