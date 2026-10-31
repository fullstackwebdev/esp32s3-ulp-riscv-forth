\ GUARDRAIL: this test exists because its absence hid a real regression (P60): a scheduler change that ran
\ only the FIRST of two spawned tasks passed all 12 checks, because the host build never stepped tasks at
\ all — vm_run_tasks was called only from the ULP's main. The host now steps ready tasks after a clean load,
\ so two-task EXECUTION is testable here instead of only on the chip.
\ Both tasks must run to completion: a machine that schedules only one task prints one of these numbers.
: TA 1 . ;
: TB 2 . ;
SPAWN TA SPAWN TB
