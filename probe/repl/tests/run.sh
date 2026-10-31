#!/usr/bin/env bash
# run.sh — regression suite for the SHIPPING engine (src/uforth.c), not the prototype.
#
# Builds the host binary from the same source the ULP runs, runs EVERY tests/*.fs through
# tools/expand.c (the same src/msg_expand.h the bridge uses), and diffs against tests/<name>.expected.
#
# GUARDRAIL: adding a test must not require editing this script. The loop over tests/*.fs was written
# after the stack-wrap bug (F-115) survived months of a green suite: coverage was extended by hand
# twice, and a hand-wired runner is how a new case gets thought about and not written down.
# Put the file next to a .expected and it runs.
#
# GUARDRAIL: do not load src/line.fs here. It is P39's demo line ("2 3 + 4 * ."), so it PRINTS 20 into the
# golden output; including it makes the suite fail for a reason unrelated to any change, and the obvious
# "fix" is to regenerate the golden file — which is how a test suite quietly stops testing anything.
#
# GUARDRAIL: the engine emits ONE BYTE per message (src/msg_codes.h), so the raw stream is not the
# operator's transcript. Everything is piped through tools/expand.c, which includes the SAME header the
# bridge uses — a filter with its own mapping would prove the copy consistent and say nothing about what
# the operator receives (R9).
set -euo pipefail
cd "$(dirname "$0")/.."
export IDF_PATH=/home/user/research/esp32/esp-idf
# shellcheck disable=SC1091
. "$IDF_PATH/export.sh" >/dev/null 2>&1 || true

# GUARDRAIL: a failed build must ABORT, not fall through to the STALE binary. Without these checks a
# compile error left the previous host_suite in place, the suite ran it, and the run reported 14/14 PASS on a
# tree that would not compile — measured while removing FAULT, where the assertion error was invisible until
# the pullout ran the assert on a re-run. Same rule as "a green suite must never be achieved by recording a
# gap": it must also never be achieved by running the wrong binary.
gcc -O2 -fno-strict-aliasing -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=2048 \
    -o artifacts/host_suite src/uforth.c || { echo "BUILD FAILED: host_suite will not compile" >&2; exit 1; }
gcc -Os -o artifacts/expand tools/expand.c
# GUARDRAIL: the block layer is compiled out of the plain host build, so a block test against it would only
# prove that BLOCK is unknown. A SECOND binary carries the shipping block flags, and tests named blocks*.fs
# run against that one — the flag set lives here, next to the engine, not in the test file.
gcc -O2 -fno-strict-aliasing -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=1200 \
    -DP33_BLOCK -DBLKPRIM -DBLKSZ=128 -DBLK_MB=4 -DOVL_LOAD -o artifacts/host_blk src/uforth.c \
    || { echo "BUILD FAILED: host_blk will not compile" >&2; exit 1; }

fail=0
for f in tests/*.fs; do
    name=$(basename "$f" .fs)
    want="tests/$name.expected"
    [ -f "$want" ] || { echo "FAIL  $name: no $want" >&2; fail=1; continue; }
    # The host loader's own "<file>:<line>: error" line is a driver diagnostic, not machine output.
    # Its presence is NOT asserted here: each error test carries its own 888 abort sentinel instead,
    # so the test says what it means without this script knowing how an abort is implemented.
    case "$name" in
        blocks*) BIN=artifacts/host_blk ;;
        # GUARDRAIL: overlay.fs needs the BLOCK-flag binary too - it was matched by the default arm and
        # ran against host_suite, which has no LOAD, so the overlay prelude failed to compile and the
        # transcript read `LOAD?` instead of the eight assertions. A test built for one flag set must
        # be routed to the binary built with that flag set.
        overlay*) BIN=artifacts/host_blk ;;
        *)       BIN=artifacts/host_suite ;;
    esac
    # GUARDRAIL: `SRV ` is the host driver's own end-of-run summary of the fake block server, and a
    # driver diagnostic must not be part of a golden transcript — it made the expected file depend on the
    # fake server's final state rather than on the program's behaviour.
    extra=""; case "$f" in *overlay*) extra=src/p39b_overlay.fs;; esac
    got=$(timeout 120 ./"$BIN" src/p39_prelude.fs $extra "$f" 2>&1 \
          | grep -a -v ': error$' | grep -a -v '^SRV ' | ./artifacts/expand || true)
    if [ "$got" = "$(cat "$want")" ]; then
        echo "PASS  $name.fs (${#got} bytes)"
    else
        echo "FAIL  $name.fs" >&2
        echo "  want: $(cat "$want")" >&2
        echo "  got : $got" >&2
        fail=1
    fi
done

# The drain's "the message does not fit this pass" path can livelock the console, and it only fires when
# the staging buffer is nearly full — so it is never seen in normal use and must be driven directly.
gcc -Os -o artifacts/ring_test tools/ring_test.c
if timeout 30 ./artifacts/ring_test >/dev/null; then
    echo "PASS  ring drain: order, completeness, no double-consume, no livelock"
else
    echo "FAIL  ring drain" >&2; fail=1
fi

# The expansion table has a failure mode of its own: an unknown code must name itself, never print
# nothing (an empty reply is indistinguishable from a healthy line).
# GUARDRAIL: use a code that is genuinely unlisted. 0x8a was the probe byte until the block layer claimed it
# for ERR_BUSY, at which point this check silently started passing the wrong thing (it printed ERR_BUSY and
# failed) — a "prove the failure path" test is only as good as the malformed input it uses.
unk=$(printf '\x91' | ./artifacts/expand)
case "$unk" in
    *"ERR_ULPCODE 0x91"*) echo "PASS  unknown message code is named" ;;
    *) echo "FAIL  unknown code printed '$unk'" >&2; fail=1 ;;
esac

# GUARDRAIL: the suite reports BEHAVIOUR only. It used to end with `./countdown.sh`, a third reporter of the
# image budget: after the app-space re-bake it printed "app space 354 B, 131 B free pool" for a lever — two
# different headroom figures in one line, neither of them earned. Pool is owned by flash_safe.sh (which
# REFUSES to flash when over) and app space by tools/bake.sh (which prints code/headers/free from the image
# it just baked). A number reported by three tools is a number that will disagree with itself.
exit $fail
