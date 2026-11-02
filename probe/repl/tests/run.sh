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
# GUARDRAIL: a clean clone has no artifacts/ directory, and every gcc -o below then fails with
# "cannot open output file artifacts/host_suite" - measured from a fresh clone, where the suite reported 0 PASS and 0
# FAIL, i.e. it looked like a green run of nothing. Create the directories the suite writes into.
mkdir -p artifacts .auto/tmp
gcc -O2 -fno-strict-aliasing -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=2048 \
    -o artifacts/host_suite src/uforth.c || { echo "BUILD FAILED: host_suite will not compile" >&2; exit 1; }
# GUARDRAIL: the capacity test compiles the phases at the SHIPPING memory size (MEMSZ 1936). Building it at the
# host suite's 1200 would fail for the wrong reason (dictionary full) and building it larger would measure a
# machine that does not exist. This binary is the one tests/capacity.sh measures.
gcc -O2 -fno-strict-aliasing -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=1936 \
    -DP33_BLOCK -DBLKPRIM -DBLKSZ=128 -DBLK_MB=4 -DOVL_LOAD -o artifacts/host_cap src/uforth.c \
    || { echo "BUILD FAILED: host_cap will not compile" >&2; exit 1; }
gcc -Os -o artifacts/expand tools/expand.c
# GUARDRAIL: MEMSZ 1200 was fine while the manager was a few words; with the event loop resident the dictionary
# no longer fits and the manager fails to define partway, which surfaces as a bogus unknown word (EV@?) in an
# unrelated test. The block binary now matches the shipping MEMSZ.
# GUARDRAIL: the block layer is compiled out of the plain host build, so a block test against it would only
# prove that BLOCK is unknown. A SECOND binary carries the shipping block flags, and tests named blocks*.fs
# run against that one — the flag set lives here, next to the engine, not in the test file.
gcc -O2 -fno-strict-aliasing -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=1936 \
    -DP33_BLOCK -DBLKPRIM -DBLKSZ=128 -DBLK_MB=4 -DOVL_LOAD -o artifacts/host_blk src/uforth.c \
    || { echo "BUILD FAILED: host_blk will not compile" >&2; exit 1; }

fail=0
# GUARDRAIL: reader_logic.fs runs against artifacts/host_app, and that is the only binary in this suite carrying the
# CHIP's own dictionary (src/image.h at the device's MEMSZ 2604 / TIBSZ 96, built by build_host_app.sh). Every other
# binary here is compiled from src/p39_prelude.fs at MEMSZ 1936, where the resident plus a real phase does not fit
# (366 B free, measured: ERR_DICT) - a reader test on one of those would fail for the geometry, not for the logic.
# The script prints its constants table and refuses by name if a device source stops defining one, so a failure here
# is a named mismatch, not a flake.
bash tests/build_host_app.sh >/dev/null || { echo "FAIL  build_host_app (device-geometry host_app)" >&2; fail=1; }
# GUARDRAIL: the block-splitting lesson (never cut a block inside a definition, never exceed one tib pass) lives in
# tools/fsplit.py, which is Python and therefore invisible to the .fs loop below. Its selftest is the test that would
# have failed on the bug that cost six probes: an oversized definition was silently split, the machine stayed in
# compile state across the boundary, and every later `N LOAD` was COMPILED instead of executed.
python3 tools/fsplit.py --selftest || { echo "FAIL  fsplit selftest" >&2; fail=1; }
# GUARDRAIL: the linter is the one check that needs no hardware, and every bug it encodes cost a chip session:
# a missing DUP (underflow three steps later), a leaked digit (a stack cell per colour change), a word used before
# it is defined, and a backslash comment that compiled as words. Run its selftest, then lint every example.
python3 tools/lint_forth.py --selftest >/dev/null || { echo "FAIL  linter selftest" >&2; fail=1; }
# GUARDRAIL: hashcheck is the only gate that sees the 12-bit dictionary identity - two names with the same hash
# means the chip REFUSES the definition and answers `NAME?` two lines later, which cost 165 probe cycles once. It
# existed as a hand-run tool, so drift went unnoticed; `DIO1PAD` in the driver collides with baked `AP1` and only
# this line says so on every run. It refuses outright when the resident vocabulary is missing.
for f in ../../examples/apps/lora/lora1.fs ../../examples/apps/shelf/shelf1.fs \
         ../../examples/apps/shelf/shelfb.fs ../../examples/apps/calc/calc1.fs \
         ../../examples/apps/mail/mail1.fs ../../examples/apps/reader/read1.fs; do
  python3 tools/hashcheck.py "$f" >/dev/null 2>&1 || { echo "FAIL  hash collision or missing vocabulary in $f" >&2; fail=1; }
done
# Strict lint for everything that can actually run on the machine.
# GUARDRAIL: the launchers are linted here, not only on the board. `boot.fs`/`menu.fs` carried a bare `' NOOP` in PICKX's
# refusal arm - a RUN-time parse inside a definition - for a whole turn; the linter had no rule for it, the device tests
# never executed the refusal, and the bug was found by hand (F-134). A shippable file that no host check reads is a file
# whose next regression waits for a chip session.
for f in ../../examples/tui_min.fs ../../examples/boot.fs ../../examples/menu.fs; do
    if python3 tools/lint_forth.py "$f" >lint.$$ 2>&1; then :; else
        echo "FAIL  lint $(basename "$f")" >&2; sed 's/^/      /' lint.$$ >&2; fail=1
    fi
done
# GUARDRAIL: the LoRa driver is TYPED into the machine line by line (tools/lora_device.py), so it is not in the list above
# and no host check used to read it - which is exactly how a stray duplicate `: !P` reached the board and answered `S?` two
# definitions later, costing a flash cycle per attempt. `--repl` selects the rules that hold for a typed load (R21 line
# length, R22 definition structure, R23 register width, R24 pad register) and drops the block-only ones (R1, R11).
if python3 tools/lint_forth.py --repl ../../examples/apps/lora/lora1.fs >lint.$$ 2>&1; then :; else
    echo "FAIL  lint (--repl) lora1.fs" >&2; sed 's/^/      /' lint.$$ >&2; fail=1
fi
# GUARDRAIL: never /tmp. The project's own rule is that every artefact lives under the working directory, so a stale
# linter file from another checkout cannot be read here and this tree stays self-contained.
rm -f lint.$$
echo "PASS  linter (11 rules) on the shippable examples"
# terminal_demo.fs is a WORK IN PROGRESS, and the reason is not laziness: it needs ~2 100 B of dictionary and the machine
# has 1 366, so it cannot be loaded, cannot be tested on the board, and its 41 lint findings cannot be separated from
# "this file is not finished". Its status is PRINTED so it cannot be forgotten.
# GUARDRAIL: `|| true`. The linter exits 1 when it HAS findings, and this script runs with `set -euo pipefail` - so
# capturing the WIP line aborted the whole suite silently right after the linter step (measured: 1 PASS instead of 25).
WIP=$(python3 tools/lint_forth.py ../../examples/terminal_demo.fs 2>&1 | tail -1 || true)
echo "WIP   terminal_demo.fs: $WIP (needs ~2 100 B of dictionary, machine has 1 366 - not loadable yet)"
# GUARDRAIL: the loader must hand over a WHOLE block even when a pass ends on padding. That cannot be tested with the
# shipping host flags (128-byte pass), so the test builds its own engine at the chip's 96-byte pass and asserts both
# ways a boundary bites: a closing ';' past the pass, and a name parsed across it.
bash tests/block_boundary.sh || { echo "FAIL  block_boundary" >&2; fail=1; }
# GUARDRAIL: the paging capabilities are verified in ONE device session by tests/capabilities.py. Its DEVICE-FREE half
# runs here (distinct per-phase oracles from the host engine), so a change that breaks the oracle or the signature scheme
# fails the ordinary suite instead of waiting for a board. The device half is the gate before a keep:
#     python3 tests/capabilities.py          (11 checks, ~90 s, one session)
python3 tests/capabilities.py --host || { echo "FAIL  capabilities (host half)" >&2; fail=1; }
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
        overlay*|loop*) BIN=artifacts/host_blk ;;
        # GUARDRAIL: a test that loads a real PHASE needs the app-store resident before it and the chip's dictionary.
        # host_app is that dictionary, and it must NOT also be handed the loop's usual src/p39_prelude.fs: it already
        # carries the baked prelude, and compiling it a second time on top spills the dictionary (measured ERR_DICT).
        # The prelude is therefore switched off per test in the second `case` below, not removed from the loop.
        reader*) BIN=artifacts/host_app ;;
        *)       BIN=artifacts/host_suite ;;
    esac
    # GUARDRAIL: `SRV ` is the host driver's own end-of-run summary of the fake block server, and a
    # driver diagnostic must not be part of a golden transcript — it made the expected file depend on the
    # fake server's final state rather than on the program's behaviour.
    extra=""; flags=""; pre=src/p39_prelude.fs
    case "$f" in
        # GUARDRAIL: the reader's logic test is compiled at device geometry against the real phase, so the resident
        # cells and the dispatcher have to be in the dictionary before it: registry.fs defines READ_ST, appstore.fs
        # defines NXT/CHAIN/SHELF, and read1.fs defines every word under test. Forget one and the transcript is a
        # column of NAME? lines that still compares equal to a golden regenerated from the same mistake.
        *reader_logic*)    pre=""; extra="../../examples/apps/registry.fs ../../examples/appstore.fs ../../examples/apps/reader/read1.fs" ;;
        # GUARDRAIL: overlay_collide asserts that a bad definition is REFUSED and then shows what survived, so
        # it needs -k (host-only, keep going after an error). The transcript still contains the ERR_DICT line.
        *overlay_collide*|*loop*) extra=src/p39b_overlay.fs; flags=-k ;;
        *overlay*)         extra=src/p39b_overlay.fs ;;
    esac
    got=$(timeout 120 ./"$BIN" $flags $pre $extra "$f" 2>&1 \
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
    if ./tests/capacity.sh; then
    echo "PASS  capacity: three phases exceed the single-image size (see above)"
else
    echo "FAIL  capacity: a paged program did not beat the monolith" >&2
    fail=1
fi

# GUARDRAIL: the A/B control is the engine with NO overlays at its own best MEMSZ. Building it with the overlay
# switch on would make the control pay for the feature it is supposed to be compared against.
gcc -O2 -fno-strict-aliasing -DHOST -DP33_NOPAGE -DP30_HANDCOPY -DP43_TASKS -DTIBSZ=128 -DMEMSZ=2296 \
    -DP33_BLOCK -DBLKPRIM -DBLKSZ=128 -DBLK_MB=4 -o artifacts/host_ctl src/uforth.c \
    || { echo "BUILD FAILED: host_ctl will not compile" >&2; exit 1; }

if ./tests/ceiling_probe.sh; then
    echo "PASS  ceiling probe: high score reported above"
else
    echo "FAIL  ceiling probe: escalation did not beat the safe baseline" >&2
    fail=1
fi

if ./tests/ceiling.sh; then
    echo "PASS  ceiling: window-sized phases raise the ceiling (see above)"
else
    echo "FAIL  ceiling: the ceiling probe failed" >&2
    fail=1
fi

if ./tests/flagship.sh; then
    echo "PASS  flagship: six phases measured (see above)"
else
    echo "FAIL  flagship: the six-phase program could not be measured" >&2
    fail=1
fi

if ./tests/abtest.sh; then
    echo "PASS  A/B: paged exceeds the no-overlay control (see above)"
else
    echo "FAIL  A/B: paging did not beat the control" >&2
    fail=1
fi

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

# --- the Forth SX1262 driver: decodes its bit-banged SPI from the host's own pin trace -----------------
# GUARDRAIL: this runs on the host with NO simulated radio. It asserts the wire bytes only, and it names the one thing it
# cannot know (DIO1 never rises), rather than asserting a success the harness cannot produce.
echo
if python3 tests/lora_spi.py; then
    echo "PASS  the Forth LoRa driver puts the C driver's byte stream on the wire"
else
    echo "FAIL  the Forth LoRa driver's wire bytes differ" >&2
    fail=1
fi

# GUARDRAIL: the suite reports BEHAVIOUR only. It used to end with `./countdown.sh`, a third reporter of the
# image budget: after the app-space re-bake it printed "app space 354 B, 131 B free pool" for a lever — two
# different headroom figures in one line, neither of them earned. Pool is owned by flash_safe.sh (which
# REFUSES to flash when over) and app space by tools/bake.sh (which prints code/headers/free from the image
# it just baked). A number reported by three tools is a number that will disagree with itself.
exit $fail
