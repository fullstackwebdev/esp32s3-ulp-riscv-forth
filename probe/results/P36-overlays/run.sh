#!/bin/bash
# P36 driver: host build + the five proofs, then the raw-path hole, each run under its own timeout.
set -x
cd "$(dirname "$0")"
./host.sh
[ -x artifacts/host_seg ] || { echo "BLOCKED: no host_seg"; exit 1; }
W="src/control.fs src/pre.fs src/paging.fs src/seg.fs"
timeout 20 nice -n 10 ./artifacts/host_seg $W src/t_seg.fs > logs/t_seg.out 2>&1
echo "SEG_EXIT=$?"
timeout 20 nice -n 10 ./artifacts/host_seg $W src/t_swap.fs > logs/t_swap.out 2>&1
echo "SWAP_EXIT=$?"
# GUARDRAIL: t_raw.fs needs a saved segment and an entry called at top level; it was written and NOT
# run in this probe — run it before citing "the raw path is silent" as executed evidence.
timeout 20 nice -n 10 ./artifacts/host_seg $W src/t_raw.fs > logs/t_raw.out 2>&1
echo "RAW_EXIT=$?"
