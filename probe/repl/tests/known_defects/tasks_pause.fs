\ GUARDRAIL: KNOWN DEFECT, not a passing test. Two tasks that PAUSE must interleave: PC prints 1, yields to
\ PD which prints 3, PD yields back, PC prints 2, PD prints 4 — every digit 1..4 exactly once. The machine
\ instead prints 122 (or 1212, variably): a paused task's continuation is copied into the record of the
\ task being started, so the second task resumes in the first task's body. Confirmed on the DEVICE, not just
\ the host. This file is kept OUT of tests/*.expected on purpose — recording "122" as the gold would be
\ recording a gap. It is run by tools/known_defects.sh and reported, never green.
: PC 1 . PAUSE 2 . ;
: PD 3 . PAUSE 4 . ;
SPAWN PC SPAWN PD
