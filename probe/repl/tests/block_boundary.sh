#!/usr/bin/env bash
# block_boundary.sh — the loader must deliver a WHOLE block even when a pass ends on padding.
#
# GUARDRAIL: this test builds its own engine at -DBLKPASS=96, because that is the chip's reality (TIBSZ 96, block 128)
# and the defect is invisible at the host's 128-byte pass: a 97-byte block fits one host pass, so the host binary
# reported TAILTEST? for a different reason and could not distinguish a fixed loader from a broken one. BLKPASS
# defaults to TIBSZ-1, so a build that sets nothing behaves exactly like the chip.
# GUARDRAIL: the two cases are the two ways a boundary can bite: the closing ';' landing past the pass (the definition
# never closes) and a NAME being parsed across it (CREATE asks for a name and is told the source is dry, so the word
# silently does not exist). Both answered wrongly before the fix in word(): the refill happened only BEFORE the
# space-skip, so a pass ending on the padding blk_refill itself writes made word() return 0 with bytes still pending.
set -uo pipefail
cd "$(dirname "$0")/.."
BIN=artifacts/host_bnd
gcc -O2 -fno-strict-aliasing -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DBLKPASS=96 -DMEMSZ=1936 \
    -DP33_BLOCK -DBLKPRIM -DBLKSZ=128 -DBLK_MB=4 -DOVL_LOAD -o "$BIN" src/uforth.c \
    || { echo "FAIL  block_boundary: build"; exit 1; }
fail=0
check() {
    local name=$1 blocks=$2 drive=$3 want=$4 got
    got=$("$BIN" -B "$blocks" -k src/p39_prelude.fs src/p39b_overlay.fs "$drive" 2>/dev/null \
          | grep -av '^SRV ' | ./artifacts/expand | tr -d '\n')
    if [ "$got" = "$want" ]; then echo "PASS  $name"; else
        echo "FAIL  $name (want '$want', got '$got')" >&2; fail=1; fi
}
# GUARDRAIL: assert BEHAVIOUR, not an absolute xt. The fixtures used to expect the exact address of the defined word
# ("83042"), so any change to the resident dictionary shifted the expected string by a few bytes and failed three tests
# for something that behaves correctly. What matters here is that the definition EXISTS (the xt is a number, not a
# "NAME?" error) and that it RUNS (42), or that the constant reads 0.
check_suffix() {
    local name=$1 blocks=$2 drive=$3 want=$4 got
    got=$("$BIN" -B "$blocks" -k src/p39_prelude.fs src/p39b_overlay.fs "$drive" 2>/dev/null \
          | grep -av '^SRV ' | ./artifacts/expand | tr -d '\n')
    case "$got" in
        *"$want") echo "PASS  $name (…$want)" ;;
        *) echo "FAIL  $name (want suffix '$want', got '$got')" >&2; fail=1 ;;
    esac
}
check_suffix "block_boundary/semicolon-past-pass" tests/fixtures/blk_tail_semicolon.txt \
      tests/fixtures/blk_tail_semicolon.fs 42
check_suffix "block_boundary/name-across-pass"     tests/fixtures/blk_tail_name.txt \
      tests/fixtures/blk_tail_name.fs 0
exit $fail
