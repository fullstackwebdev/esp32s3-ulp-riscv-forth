\ exp_l.fs - the boot16.fs IF, in ten lines. Load with boot16.fs (P33's shipped prelude).
\   timeout 5 host_blocks boot16.fs exp_l.fs
\ Every line is a colon definition on purpose: top-level IF does not branch anything.
: T     ( f -- ) IF ." PASS" 10 EMIT EXIT THEN ." FAIL" 10 EMIT ;
: TRUE-IF  0 0= T ;      \ the branch is taken (skip the body)
: FALSE-IF 1 0= T ;      \ the branch falls through (run the body)
." L-true  " TRUE-IF
." L-false " FALSE-IF
." L-done  " 10 EMIT
