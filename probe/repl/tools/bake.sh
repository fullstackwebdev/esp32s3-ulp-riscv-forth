#!/bin/sh
# Bake src/image.h — the compiled prelude and its dictionary — at the SHIPPING flag set.
#
# Why this file exists: the bake flag set has to match the ULP build exactly, and it was previously a
# hand-typed command in a probe doc. Passing MEMSZ here and interpolating it there is not a detail — the
# baked image embeds V_LATEST as an ABSOLUTE address (it is the base of the header area), so a bake at one
# MEMSZ and a build at another points the dictionary outside mem[] and every word reads as unknown.
#
#   GUARDRAIL: one owner for the bake flags. Duplicating them in a shell command is how the shipping image
#   came to be baked at MEMSZ 1900 while the ULP built at 1704 (E-079): the link succeeded, the image was
#   "valid", and the chip answered WORD? to everything.
#   GUARDRAIL: MEMSZ is an argument here and MUST equal ulp_repl.c's MEMSZ. tools/bake.sh prints the three
#   numbers (code / headers / free gap) so the caller can compare against countdown.sh instead of trusting it.
#
# usage: tools/bake.sh [MEMSZ]
set -e
cd "$(dirname "$0")/.."

MEMSZ=${1:-1400}
FLAGS="-O2 -fno-strict-aliasing -DHOST -DP43_TASKS -DP33_BLOCK -DBLKPRIM -DBLKSZ=128 -DBLK_MB=4 -DTIBSZ=128 -DP33_NOPAGE -DP30_HANDCOPY -DMEMSZ=$MEMSZ"

# GUARDRAIL: -DP33_BLOCK without -DBLKPRIM (or the reverse) compiles and links and produces a dictionary
# with no BLOCK words — the failure is a "WORD?" on the chip, not a build error (E-079).
gcc $FLAGS -o artifacts/bake_bin src/uforth.c

# GUARDRAIL: the prelude AND line.fs. Baking without line.fs bakes a dictionary that cannot load a file,
# i.e. no way to add words at the prompt.
./artifacts/bake_bin -d src/image.h src/p39_prelude.fs src/line.fs

echo "baked src/image.h at MEMSZ=$MEMSZ"
head -1 src/image.h
