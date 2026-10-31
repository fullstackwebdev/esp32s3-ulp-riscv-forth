#!/bin/sh
# P19: one run per layout per build; every run under `timeout 30` and redirected to its own log.
# GUARDRAIL: the sim opens "faults.log" and "boot_min.fs" relative to the cwd, so each run must be
# launched from its own directory and its faults.log renamed immediately — two layouts sharing one
# faults.log is how P03f nearly lost the 390-fault cycle it quotes.
set -u
for tag in 4x512 3x512 2x512 4x256; do
  ( cd . && timeout 30 ./paging_sim-$tag > run-$tag.log 2>&1; echo "work $tag exit=$?" ; mv -f faults.log faults-$tag.log 2>/dev/null )
  ( cd rmw && timeout 30 ./paging_sim-$tag > run-rmw-$tag.log 2>&1; echo "rmw  $tag exit=$?" ; mv -f faults.log faults-rmw-$tag.log 2>/dev/null )
done
