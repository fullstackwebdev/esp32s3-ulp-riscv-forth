#!/usr/bin/env bash
# transcript.sh — prove requirement 1 (zero loss of readability) on the host, without the board.
#
# Builds TWO host engines from the same source the ULP runs: src_base/uforth.c (the pristine copy, i.e.
# today's behaviour) and src/uforth.c (message codes). Each one's stdout is the exact byte stream it
# would push into the out ring. The coded stream is then passed through tools/expand.c — the same
# src/msg_expand.h the bridge uses — and the two transcripts are compared byte for byte.
#
# GUARDRAIL: the baseline run is diffed against tests/expected.txt FIRST. If the pristine copy does not
# reproduce the shipping regression suite, the comparison below is between two unknown programs (R9).
set -euo pipefail
cd "$(dirname "$0")/.."
R=../../repl                      # read-only: prelude + suite, the shipping golden files
OUT=out
mkdir -p "$OUT"
FLAGS="-O2 -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=2048"

gcc $FLAGS -o "$OUT/host_base"  src_base/uforth.c
gcc $FLAGS -o "$OUT/host_coded" src/uforth.c
gcc -O2 -o "$OUT/expand" tools/expand.c

run_base()  { timeout 30 "$OUT/host_base"  "$R/src/p39_prelude.fs" "$R/tests/suite.fs" 2>&1 || true; }
run_coded() { timeout 30 "$OUT/host_coded" "$R/src/p39_prelude.fs" "$R/tests/suite.fs" 2>&1 || true; }

run_base  > "$OUT/t_base.txt"
run_coded > "$OUT/t_coded_raw.txt"
"$OUT/expand" < "$OUT/t_coded_raw.txt" > "$OUT/t_coded.txt"

# 1. the baseline must be the shipping program, or the comparison means nothing.
#    Command substitution strips the trailing newline on both sides, exactly as tests/run.sh does:
#    the engine never ends a transcript with a newline, the golden file does.
if [ "$(cat "$R/tests/expected.txt")" != "$(cat "$OUT/t_base.txt")" ]; then
    echo "FAIL  baseline does not reproduce tests/expected.txt" >&2
    diff -u "$R/tests/expected.txt" "$OUT/t_base.txt" >&2 || true
    exit 1
fi
echo "PASS  baseline == tests/expected.txt ($(wc -c < "$OUT/t_base.txt") B)"

# 2. the transcript must be byte-identical (file-driven path)
if ! cmp -s "$OUT/t_base.txt" "$OUT/t_coded.txt"; then
    echo "FAIL  expanded transcript differs from today's" >&2
    diff -u "$OUT/t_base.txt" "$OUT/t_coded.txt" >&2 || true
    exit 1
fi
echo "PASS  file-suite transcript byte-identical"

# 3. Interactive path (forth_quit). This is the ONLY place the file suite's messages are reachable:
#    load() prints nothing on success, so " ok\n" / the erase sequence / "stack?\n" never appear in the
#    file run above. The number of code bytes is asserted non-zero — identical output would also "match"
#    if the edit had never been compiled in (R9).
#    GUARDRAIL: feed stdin from a FILE, not from a variable. Command substitution strips trailing newlines,
#    so `script=$(printf '...\n')` loses the last newline, forth_quit() reads EOF mid-line, exits(0)
#    without processing that line — and both sides of the diff agree that nothing happened. The overflow
#    message then looks "verified" when it was never reached.
printf '1 2 + .\n5\b\x7f9\nBOGUS\n1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1\n' > "$OUT/in.txt"
timeout 30 "$OUT/host_base"  -i < "$OUT/in.txt" > "$OUT/i_base.txt" 2>&1 || true
timeout 30 "$OUT/host_coded" -i < "$OUT/in.txt" > "$OUT/i_coded_raw.txt" 2>&1 || true
"$OUT/expand" < "$OUT/i_coded_raw.txt" > "$OUT/i_coded.txt"
codes=$(python3 -c 'import sys;d=open(sys.argv[1],"rb").read();print(sum(1 for b in d if b>=0x80))' "$OUT/i_coded_raw.txt")
[ "$codes" -gt 0 ] || { echo "FAIL  no code bytes in the interactive stream — the edit is not in the measurement" >&2; exit 1; }
echo "PASS  interactive stream: $codes code bytes, $(python3 -c 'import sys;d=open(sys.argv[1],"rb").read();print(sum(1 for b in d if b<0x80))' "$OUT/i_coded_raw.txt") ASCII bytes"
if ! cmp -s "$OUT/i_base.txt" "$OUT/i_coded.txt"; then
    echo "FAIL  interactive transcript differs" >&2
    diff -u "$OUT/i_base.txt" "$OUT/i_coded.txt" >&2 || true
    exit 1
fi
echo "PASS  interactive transcript byte-identical ($(wc -c < "$OUT/i_base.txt") B)"
printf '      baseline: %s\n' "$(od -c "$OUT/i_base.txt" | head -4 | tr -s ' ' | tr '\n' '|')"
printf '      coded   : %s\n' "$(python3 -c 'import sys;print(repr(open(sys.argv[1],"rb").read()))' "$OUT/i_coded_raw.txt")"


# 4. the task-table refusal (tests/ntsk.fs) is the only *reachable* named engine error, and it is the
#    one that must still name itself (an unknown word prints the word from PAD, a full table prints
#    ERR_TASKS — the distinction that cost a debugging session in P6x).
timeout 30 "$OUT/host_base"  "$R/src/p39_prelude.fs" "$R/tests/ntsk.fs" > "$OUT/n_base.txt"  2>&1 || true
timeout 30 "$OUT/host_coded" "$R/src/p39_prelude.fs" "$R/tests/ntsk.fs" > "$OUT/n_raw.txt"   2>&1 || true
"$OUT/expand" < "$OUT/n_raw.txt" > "$OUT/n_coded.txt"
if ! cmp -s "$OUT/n_base.txt" "$OUT/n_coded.txt"; then
    echo "FAIL  ntsk transcript differs" >&2
    diff -u "$OUT/n_base.txt" "$OUT/n_coded.txt" >&2 || true
    exit 1
fi
python3 -c 'import sys;d=open(sys.argv[1],"rb").read();sys.exit(0 if b"\x88" in d else 1)' "$OUT/n_raw.txt" \
    || { echo "FAIL  ERR_TASKS did not travel as code 0x88" >&2; exit 1; }
echo "PASS  task-table refusal byte-identical, travelled as code 0x88: $(cat "$OUT/n_coded.txt")"

# 5. fail loud: an unlisted code must produce a named error, never silence
printf 'abc\x90def' | "$OUT/expand" > "$OUT/bad.txt"
grep -q 'ERR_ULPCODE 0x90' "$OUT/bad.txt" || { echo "FAIL  unknown code 0x90 was silent" >&2; exit 1; }
echo "PASS  unknown code 0x90 -> $(cat "$OUT/bad.txt" | tr -d '\n')"
