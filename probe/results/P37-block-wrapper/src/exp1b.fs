\ exp1b.fs - P37 experiment 1, the hanging half. This file is EXPECTED to hang.
\   timeout 5 host_blocks boot37.fs exp1b.fs
\ The flag is cleared and only the host could set it again, but the host runs between interpreter
\ steps and the spin never returns to one: no hook exists that can write FLAG during a dispatch.
\ That is the harness's *definition*, not a defect of the compiled loop — exp1a already showed the
\ same loop terminating when the value is there before the call.
CREATE FLAG 0 ,
: SPINF ( -- ) BEGIN FLAG @ UNTIL ;
: T ( f -- ) IF ." PASS" 10 EMIT EXIT THEN ." FAIL" 10 EMIT ;
." e1-live-clear " 0 FLAG !
." e1-live-spin  " SPINF ." FAIL-terminated" 10 EMIT
