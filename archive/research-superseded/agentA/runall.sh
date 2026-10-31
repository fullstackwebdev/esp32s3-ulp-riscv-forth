#!/usr/bin/env bash
# runall.sh — the canonical measurement run. One row per variant, in the order FINDINGS.md quotes them,
# plus the host check for each shape. Re-running this reproduces every number in FINDINGS.md.
# GUARDRAIL: every row goes through measure.sh, which re-measures `base` and prints its sha256 — if that
# sha ever stops matching the shipping ELF, every delta below it is invalid and must be re-derived, not
# re-quoted (R9).
set -uo pipefail
cd "$(dirname "$0")"
: > RESULTS.txt
row() { local n=$1; shift
  timeout 600 nice -n 15 ./measure.sh "$n" "$@" 2>&1 | grep -v "^ *-I" | grep -E "^\S+ +elf|failed" | tee -a RESULTS.txt
}
check() { local n=$1; shift
  ./verify.sh "$n" "$@" 2>&1 | tee -a RESULTS.txt
}
echo "== engine shapes (TASK 1 + TASK 2) ==" | tee -a RESULTS.txt
row base
check base
row cgoto   -DVM_CGOTO                                     ; check cgoto   -DVM_CGOTO
row uc      -DUC_ACCESS                                    ; check uc      -DUC_ACCESS
row cgoto_uc -DVM_CGOTO -DUC_ACCESS                        ; check cgoto_uc -DVM_CGOTO -DUC_ACCESS
row fold    -DUC_ACCESS -DUC_FOLD                          ; check fold    -DUC_ACCESS -DUC_FOLD
row cgoto_fold -DVM_CGOTO -DUC_ACCESS -DUC_FOLD            ; check cgoto_fold -DVM_CGOTO -DUC_ACCESS -DUC_FOLD
row cgoto_fold_f -DVM_CGOTO -DUC_ACCESS -DUC_FOLD -DUC_FETCH ; check cgoto_fold_f -DVM_CGOTO -DUC_ACCESS -DUC_FOLD -DUC_FETCH
row cgoto_uc_ni -DVM_CGOTO -DUC_ACCESS -DUC_NOINLINE
row cgoto_ucstack -DVM_CGOTO -DUC_ACCESS -DUC_STACK
row cgoto_ucall -DVM_CGOTO -DUC_ACCESS -DUC_ALL
row cgoto_ucall_fold -DVM_CGOTO -DUC_ACCESS -DUC_FOLD -DUC_ALL
echo "== compiler levers on base (TASK 3) ==" | tee -a RESULTS.txt
for f in "-mrelax" "-fno-jump-tables" "-ftree-switch-conversion" "-fno-tree-switch-conversion" \
         "-mcmodel=medlow" "-mcmodel=medany" "-fira-region=all" "-falign-functions=1" \
         "-fomit-frame-pointer" "-fno-omit-frame-pointer" "-Oz" "-mno-save-restore" \
         "-fno-crossjumping" "-falign-functions=2 -falign-jumps=2 -falign-loops=2" \
         "-fno-ipa-icf" "-fmerge-all-constants" "-fira-algorithm=priority" "-fno-inline" \
         "-finline-functions" "-fconserve-stack"; do
  row "lev${f//[^A-Za-z0-9]/_}" $f
done
LINK_EXTRA=-mrelax row lev_mrelax_at_link -mrelax
LINK_EXTRA=-Wl,--relax row lev_relax_at_link -mrelax
# GNU ld has no --icf (it is an lld option); the row is recorded as a FAILED build, not as a zero.
LINK_EXTRA="-Wl,--icf=all" row lev_icf_at_link
echo "== compiler levers on the winning shape (cgoto_fold) ==" | tee -a RESULTS.txt
for f in "-mrelax" "-fno-jump-tables" "-Oz" "-fno-omit-frame-pointer" "-fno-crossjumping" "-fira-region=all"; do
  row "gf${f//[^A-Za-z0-9]/_}" -DVM_CGOTO -DUC_ACCESS -DUC_FOLD $f
done
