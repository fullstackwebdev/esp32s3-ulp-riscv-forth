#!/usr/bin/env bash
# build_host_app.sh — build artifacts/host_app: the engine at the CHIP's geometry, carrying the CHIP's dictionary.
#
# Why this file exists: tests/run.sh builds the engine at the suite's own geometry (MEMSZ 1936, TIBSZ 128) because
# that is the cheapest engine to test; a screen golden drawn by THAT binary is a golden for a machine that does not
# exist. Every constant below is read out of the device sources, printed, and compared - the integrator diffs the table
# against the board instead of trusting a copy of the numbers in a shell script (R6: never derive an ordering twice).
#
#   GUARDRAIL: the flag set is DERIVED from src/ulp_repl.c, not typed here. The bake flag set was once hand-typed in a
#   probe doc and drifted from the ULP build (E-079: image baked at MEMSZ 1900, ULP built at 1704, every word WORD? on
#   the chip). A constant this script cannot read is a NAMED failure, never a default.
#
#   GUARDRAIL: host_app is built with -DIMAGE, i.e. it links src/image.h — the same dictionary bytes the chip runs.
#   Loading src/p39_prelude.fs on the host instead would compile a DIFFERENT dictionary: the prelude's longest line is
#   104 characters and the device TIB is 96, so the device never loads that text at all (bake.sh loads it at TIBSZ 128
#   and the result is flashed). -DIMAGE removes the whole class: the host and the board start from identical mem[].
#
#   GUARDRAIL: TIBSZ is the device's 96, not the suite's 128, because the engine's block pass is BLKPASS = TIBSZ-1 = 95
#   and the host's line limit is TIBSZ-1 = 95 — both are exactly what the chip does. A host binary at 128 accepts a
#   100-character line that the board refuses with MSG_LINE_TOO_LONG, i.e. a phase that "works on host, fails on device".
#
# usage: tests/build_host_app.sh        (prints every constant; exits non-zero, named, on any unmatchable one)
set -euo pipefail
cd "$(dirname "$0")/.."                       # probe/repl

REPL_SRC=src/ulp_repl.c
ENGINE_SRC=src/uforth.c
IMAGE_H=src/image.h
OUT=artifacts/host_app

die() { printf '\nFAIL  %s\n      %s\n' "$1" "$2" >&2; exit 1; }

# ---- constants, read from the source that owns them ------------------------------------------------------------
# need NAME -> the value of a plain `#define NAME value` in src/ulp_repl.c (the device's own header).
need() {
    local v
    v=$(sed -n "s/^#define[[:space:]]\{1,\}$1[[:space:]]\{1,\}\([^/[:space:]]*\).*/\1/p" "$REPL_SRC" | head -1)
    [ -n "$v" ] || die "${1}_UNMATCHED" "src/ulp_repl.c has no '#define $1 <value>' any more; this script derives the host build from it, so update both"
    printf '%s\n' "$v"
}

# need_on NAME -> the switch must be #defined on the device, and this host build must define it too.
need_on() {
    grep -qE "^#define[[:space:]]+$1([[:space:]]|$)" "$REPL_SRC" \
        || die "${1}_UNMATCHED" "src/ulp_repl.c no longer defines $1; a host app built without it is a different machine"
}

MEMSZ=$(need MEMSZ)
SD=$(need SD)
TIBSZ=$(need TIBSZ)
BLKSZ=$(need BLKSZ)
BLK_MB=$(need BLK_MB)
CMD_SIZE=$(need CMD_SIZE)
OUT_SIZE=$(need OUT_SIZE)
P54=$(need P54_BINOPS)
for sw in IMAGE P33_BLOCK BLKPRIM OVL_LOAD P30_HANDCOPY P33_NOPAGE; do need_on "$sw"; done

# GUARDRAIL: P43_TASKS must be ABSENT on the device (it costs ~280 B of .bss + 200 B of text and the REPL is lost with
# it on), and `#define P43_TASKS 0` would still satisfy every `#if defined(P43_TASKS)` in the engine. So the check is
# "not defined at all", and a host app built with the scheduler would hold different .bss and a different dictionary.
if grep -qE '^#define[[:space:]]+P43_TASKS' "$REPL_SRC"; then
    die TASKS_MISMATCH "src/ulp_repl.c now defines P43_TASKS; the device dictionary changes with it - re-bake and re-check this script"
fi

# ---- run-time geometry: HDRTOP and the transfer offset, from the engine ------------------------------------------
grep -qE '^#define[[:space:]]+BLKADR[[:space:]]+\(MEMSZ - BLKSZ\)' "$ENGINE_SRC" \
    || die BLKADR_UNMATCHED "src/uforth.c no longer has '#define BLKADR (MEMSZ - BLKSZ)'; the transfer offset is no longer a difference of two constants this script can compute"
grep -qE '^#define[[:space:]]+HDRTOP[[:space:]]+BLKADR' "$ENGINE_SRC" \
    || die HDRTOP_UNMATCHED "src/uforth.c no longer has '#define HDRTOP BLKADR'; with blocks on, the header area must stay below the block buffer and this script prints it as the image's top"
BLKADR=$((MEMSZ - BLKSZ))
HDRTOP=$BLKADR

enum_of() {                                     # enum_of NAME -> its value in the engine's sys-var enum
    local v
    v=$(grep -oE "[,{[:space:]]$1[[:space:]]*=[[:space:]]*[0-9]+" "$ENGINE_SRC" | head -1 | grep -oE '[0-9]+$')
    [ -n "$v" ] || die "${1}_UNMATCHED" "src/uforth.c's sys-var enum no longer has '$1 = <n>'; PAD/DICT are the app space's floor and this script prints them"
    printf '%s\n' "$v"
}
V_STATE=$(enum_of V_STATE); V_HERE=$(enum_of V_HERE); V_LATEST=$(enum_of V_LATEST)
V_SEAL=$(enum_of V_SEAL); V_LOADB=$(enum_of V_LOADB); PAD=$(enum_of PAD); DICT=$(enum_of DICT)

# ---- the baked dictionary: same MEMSZ, same top ----------------------------------------------------------------
[ -f "$IMAGE_H" ] || die IMAGE_MISSING "src/image.h is absent: the device's dictionary IS that file (tools/bake.sh $MEMSZ). A host app that compiles its own dictionary tests a different machine"
IMAGE_LINE=$(head -1 "$IMAGE_H")
read -r IMAGE_USED IMAGE_MEMSZ <<<"$(sed -n 's#.*-d: \([0-9]\{1,\}\) of \([0-9]\{1,\}\) bytes used.*#\1 \2#p' "$IMAGE_H" | head -1)"
[ -n "${IMAGE_USED:-}" ] || die IMAGE_UNREADABLE "src/image.h's first line is not the bake header ($IMAGE_LINE); cannot prove which MEMSZ the dictionary was baked at"
[ "$IMAGE_MEMSZ" = "$MEMSZ" ] || die IMAGE_MEMSZ_MISMATCH "src/image.h was baked at MEMSZ $IMAGE_MEMSZ, the ULP builds at $MEMSZ (src/ulp_repl.c); re-bake with tools/bake.sh $MEMSZ"
[ "$IMAGE_USED" = "$HDRTOP" ] || die IMAGE_HDRTOP_MISMATCH "src/image.h used $IMAGE_USED bytes, but this build's header top is MEMSZ-BLKSZ = $HDRTOP; the dictionary's absolute header base would point outside mem[]"

# ---- the flag set, one owner -----------------------------------------------------------------------------------
FLAGS=(-O2 -fno-strict-aliasing -DHOST -DIMAGE
       -DP33_BLOCK -DBLKPRIM "-DBLKSZ=$BLKSZ" "-DBLK_MB=$BLK_MB" "-DTIBSZ=$TIBSZ"
       -DOVL_LOAD -DP33_NOPAGE -DP30_HANDCOPY "-DP54_BINOPS=$P54"
       "-DMEMSZ=$MEMSZ" "-DSD=$SD")

mkdir -p artifacts
printf '%s\n' "building $OUT from $ENGINE_SRC (gcc ${FLAGS[*]})"
# GUARDRAIL: a failed build must not leave the previous binary in place - a stale host_app reports goldens for the code
# that used to be there (tests/run.sh has the same lesson, learned on host_suite).
rm -f "$OUT"
gcc "${FLAGS[@]}" -o "$OUT" "$ENGINE_SRC" \
    || die BUILD_FAILED "gcc refused $ENGINE_SRC at the device geometry above; the errors are printed above this line"
gcc -Os -o artifacts/expand tools/expand.c \
    || die EXPAND_BUILD_FAILED "gcc refused tools/expand.c; without it the host stream carries raw src/msg_codes.h bytes"

# ---- the baked dictionary's live numbers, read out of the image itself ------------------------------------------
# GUARDRAIL: V_HERE and V_LATEST are READ from src/image.h (the first three words of mem[]), not recomputed from the
# prelude's size: the bake is the owner of those two numbers, and a second derivation of "how big is the dictionary" is
# exactly how the countdown script once printed two different headroom figures in one line (R7). They are also the two
# numbers cli.connect() judges a fresh board by (`HERE .`, `LATEST .`).
read -r BAKE_HERE BAKE_LATEST <<<"$(python3 - "$IMAGE_H" <<'PY'
import re, sys
body = open(sys.argv[1]).read().split("{", 1)[1].split("}", 1)[0]
b = [int(x, 16) for x in re.findall(r"0x([0-9a-fA-F]{2})", body)]
w = lambda o: b[o] | b[o + 1] << 8 | b[o + 2] << 16 | b[o + 3] << 24
print(w(4), w(8))
PY
)"
[ -n "${BAKE_HERE:-}" ] || die IMAGE_UNREADABLE "could not read V_HERE/V_LATEST out of $IMAGE_H; the baked image's first words are the dictionary's shape"

# ---- the table the integrator diffs against the board ---------------------------------------------------------
# On the board the same numbers are visible as `HERE .` / `LATEST .` / `bl @ .` and as the block read address 2476
# that cli.connect() prints; nothing here needs a board run to be checked.
row() { printf '  %-16s %-14s %s\n' "$1" "$2" "$3"; }
echo
row constant host_app "device source / derivation"
printf '  %s %s %s\n' "----------------" "--------------" "--------------------------------------------------------------------" || true
row MEMSZ "$MEMSZ" "$REPL_SRC '#define MEMSZ' (bytes of Forth memory)"
row SD "$SD" "$REPL_SRC '#define SD' (cells per stack)"
row TIBSZ "$TIBSZ" "$REPL_SRC '#define TIBSZ' -> BLKPASS = TIBSZ-1 = $((TIBSZ - 1))"
row BLKSZ "$BLKSZ" "$REPL_SRC '#define BLKSZ' (one block = one buffer)"
row BLK_MB "$BLK_MB" "$REPL_SRC '#define BLK_MB' (mailbox: blk op status checksum)"
row CMD_SIZE "$CMD_SIZE" "$REPL_SRC '#define CMD_SIZE'  bridge ring, NOT linked on the host"
row OUT_SIZE "$OUT_SIZE" "$REPL_SRC '#define OUT_SIZE'  bridge ring, NOT linked on the host"
row HDRTOP "$HDRTOP" "$ENGINE_SRC '#define HDRTOP BLKADR' (header base)"
row BLKADR "$BLKADR" "$ENGINE_SRC '#define BLKADR (MEMSZ - BLKSZ)' = the transfer offset"
row "sys vars" "$V_STATE/$V_HERE/$V_LATEST/$V_SEAL/$V_LOADB" "$ENGINE_SRC enum: STATE HERE LATEST SEAL LOADB"
row "PAD, DICT" "$PAD, $DICT" "$ENGINE_SRC enum (DICT = where the code area starts)"
row image.h "$IMAGE_USED/$IMAGE_MEMSZ" "$IMAGE_H first line (checked equal to HDRTOP/MEMSZ above)"
row "baked HERE" "$BAKE_HERE" "$IMAGE_H mem[4..7] = what the board answers to 'HERE .'"
row "baked LATEST" "$BAKE_LATEST" "$IMAGE_H mem[8..11] = what the board answers to 'LATEST .'"
row "app space" "$((BAKE_LATEST - BAKE_HERE)) B" "LATEST-HERE at boot: the window every phase must fit (docs/26)"
row P54_BINOPS "$P54" "$REPL_SRC '#define P54_BINOPS' (a rung number, not a boolean)"
row P43_TASKS "off" "absent in $REPL_SRC (checked above: a defined scheduler changes the dictionary)"
row "block store" "128 x $BLKSZ" "$((128 * BLKSZ)) B, the allocation docs/26 hands out"
echo
echo "  $OUT  $(stat -c%s "$OUT") B,  artifacts/expand $(stat -c%s artifacts/expand) B"
echo "  keys are fed on stdin: KEY = getchar() and EOF ends the run (see tools/screen.py)"
