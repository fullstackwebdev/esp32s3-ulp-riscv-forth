#!/bin/bash
# abtest.sh — the A/B that decides whether paging is worth its resident cost.
#
# BEFORE (control): the same program built as ONE image in an engine with no overlays (its own best MEMSZ).
#                   It must die with ERR_DICT; the point at which it dies is the real monolith ceiling.
# AFTER  (paged):   the same three phases loaded one at a time, each rewound first.
#
# PASS requires all of:
#   1. the control FAILS with ERR_DICT (if it succeeds, the program is not big enough to prove anything),
#   2. the paged build compiles MORE bytes than the control's free space,
#   3. every phase fits its own window (asserted by capacity.sh), and
#   4. the capability difference is real: the phase the control could not fit produces output only in the
#      paged build.
set -u
cd "$(dirname "$0")/.." || exit 1
CTL=artifacts/host_ctl          # no OVL_LOAD: the control
PAGED=artifacts/host_cap        # overlays on, shipping MEMSZ
PRE=src/p39_prelude.fs
PHASES="tests/capacity_a.fsx tests/capacity_b.fsx tests/capacity_c.fsx"

for b in "$CTL" "$PAGED"; do
    [ -x "$b" ] || { echo "BUILD FAILED: $b missing (run.sh builds it)" >&2; exit 1; }
done

fail=0
ctl_free=$("$CTL" "$PRE" tests/fixtures/free_probe.fs 2>&1 | grep -av '^SRV ' | tr -cd '0-9\n' | grep -E '^[0-9]+$' | tail -1)
case "$ctl_free" in ''|*[!0-9]*) echo "abtest: could not read the control's free space" >&2; exit 1;; esac
printf "  control: %d B free (no overlays, its own best MEMSZ)\n" "$ctl_free"

# 1. the control must FAIL, and its failure point is the ceiling
# GUARDRAIL: pipe through artifacts/expand. The engine emits a message CODE, not a name, so grepping the raw
# output for "ERR_DICT" finds nothing and the test reports "the control loaded the whole program" - a false
# alarm that reads like the program is too small.
ctl_out=$("$CTL" "$PRE" $PHASES 2>&1 | grep -av '^SRV ' | ./artifacts/expand)
if grep -q 'ERR_DICT' <<<"$ctl_out"; then
    printf "  control: ERR_DICT as expected - the monolith cannot hold this program\n"
else
    echo "  FAIL: the control loaded the whole program; it is not big enough to test anything" >&2; fail=1
fi

# 4. capability diff: phase C's statistics exist only in the paged build
C_DIGITS=43261644032127
if tr -cd '0-9' <<<"$ctl_out" | grep -q "$C_DIGITS"; then
    echo "  FAIL: the control produced phase C's output, so overlays added no capability" >&2; fail=1
else
    printf "  control: phase C did not run (no %s) - that is the capability gap\n" "$C_DIGITS"
fi
if ./tests/capacity.sh >/tmp/abtest_cap.out 2>&1; then
    paged_total=$(sed -n 's/.*total \([0-9]*\) B across.*/\1/p' /tmp/abtest_cap.out)
    grep -q "$C_DIGITS" /tmp/abtest_cap.out || { echo "  FAIL: the paged build did not produce phase C's output" >&2; fail=1; }
    printf "  paged:   %s B compiled across three phases (phase C runs)\n" "${paged_total:-?}"
else
    echo "  FAIL: capacity.sh failed; see its output below" >&2
    sed 's/^/    /' /tmp/abtest_cap.out >&2
    fail=1; paged_total=0
fi

# 2. the headline: paged total must exceed the control's free space
case "${paged_total:-0}" in ''|*[!0-9]*) paged_total=0;; esac
printf "  headline: %s B paged vs %s B control ceiling: " "$paged_total" "$ctl_free"
if [ "$paged_total" -gt "$ctl_free" ]; then
    echo "PASS (+$(( (paged_total - ctl_free) * 100 / ctl_free ))%)"
else
    echo "FAIL (paging bought nothing - bank the resident cost)"; fail=1
fi
rm -f /tmp/abtest_cap.out
exit "$fail"
