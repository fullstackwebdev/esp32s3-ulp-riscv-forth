#!/usr/bin/env bash
# difftest.sh — prove two source trees emit the SAME diagnostic bytes.
#
#   ./tools/difftest.sh <variant-dir>          # compares src/ (baseline) with <variant-dir>
#
# Builds the same host engines tests/run.sh builds (same flags, same prelude, same expander), runs
# EVERY tests/*.fs and src/line.fs through both, and compares the RAW byte stream, not just the text:
# the operator's transcript is a projection of those bytes through src/msg_expand.h, so a changed code
# that happens to expand to the same text today is still a wire change (msg_codes.h is APPEND ONLY).
#
# GUARDRAIL: the comparison is raw-output-against-raw-output. Diffs against the golden .expected files
# belong to tests/run.sh; doing it here would let a variant that changes BOTH engines pass.
# GUARDRAIL: report which message codes the corpus actually reached. "No differences" over a corpus
# that never emits ERR_BUFOVER is not evidence about ERR_BUFOVER, and the honest form of that gap is a
# printed coverage line, not a silent pass (that is how 0x8a was once "tested" while printing ERR_BUSY).
set -euo pipefail
cd "$(dirname "$0")/.."
VAR=${1:?usage: tools/difftest.sh <variant-dir>}
A=src
B=$VAR
mkdir -p artifacts/diff
# GUARDRAIL: two runs share artifacts/diff/base.raw and artifacts/diff/var.raw, so in parallel each cmp
# compares ONE run's baseline against the OTHER run's variant — the output is a spurious DIFF that reads
# exactly like a real diagnostic change (hit in P54-fail: pricing var_c and var_f at the same time showed
# blocks_noserver "changed" to addr.fs's output). Refuse to run concurrently instead of reporting that.
exec 9>artifacts/diff/.lock
flock -n 9 || { echo "difftest: another run holds artifacts/diff/.lock — run them one at a time" >&2; exit 3; }

build() {   # build <srcdir> <prefix>
    gcc -O2 -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=2048 \
        -o "artifacts/diff/$2_suite" "$1/uforth.c"
    gcc -O2 -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=1200 \
        -DP33_BLOCK -DBLKPRIM -DBLKSZ=128 -BLK_MB=4 -o /dev/null "$1/uforth.c" 2>/dev/null || true
    gcc -O2 -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=1200 \
        -DP33_BLOCK -DBLKPRIM -DBLKSZ=128 -DBLK_MB=4 -o "artifacts/diff/$2_blk" "$1/uforth.c"
}
build "$A" base
build "$B" var
gcc -Os -o artifacts/diff/expand tools/expand.c

fail=0
: > artifacts/diff/codes_base
: > artifacts/diff/codes_var
for f in tests/*.fs src/line.fs; do
    name=$(basename "$f" .fs)
    case "$name" in blocks*) BIN=blk ;; *) BIN=suite ;; esac
    for side in base var; do
        # shellcheck disable=SC2086
        timeout 120 ./artifacts/diff/${side}_$BIN "$A/p39_prelude.fs" "$f" >"artifacts/diff/$side.raw" 2>"artifacts/diff/$side.err" || true
        grep -a -v '^SRV ' "artifacts/diff/$side.raw" | grep -a -v ': error$' > "artifacts/diff/$side.raw2" || true
        tr -d '\000' < "artifacts/diff/$side.raw2" | od -An -tu1 > "artifacts/diff/$side.bytes"
        # every byte >= 0x81 in the stream is a message code (msg_codes.h: the engine emits nothing
        # else above 0x7f) — scan EVERY column, not just the first, or a code that follows an echo on
        # the same od line is counted as "not reached" and the coverage line lies in the safe direction.
        awk '{for (i = 1; i <= NF; i++) if ($i >= 129 && $i <= 154) print $i}' \
            "artifacts/diff/$side.bytes" >> "artifacts/diff/codes_$side"
    done
    if cmp -s artifacts/diff/base.bytes artifacts/diff/var.bytes; then
        echo "SAME  $name"
    else
        echo "DIFF  $name" >&2
        diff -u artifacts/diff/base.bytes artifacts/diff/var.bytes | head -20 >&2 || true
        fail=1
    fi
done

codes=$(sort -u artifacts/diff/codes_base | wc -l)
echo "-- message codes reached by this corpus: $codes of 16 (0x81..0x90)"
if ! cmp -s <(sort -u artifacts/diff/codes_base) <(sort -u artifacts/diff/codes_var); then
    echo "DIFF  message-code set differs" >&2
    fail=1
fi
sort -u artifacts/diff/codes_base | awk '{printf "0x%02x ", $1} END {print ""}'
exit $fail
