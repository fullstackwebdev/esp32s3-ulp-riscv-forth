\ exp1a.fs - P37 experiment 1, the terminating half: does a compiled spin run at all?
\   host_blocks boot37.fs exp1a.fs
\ GUARDRAIL: a top-level `IF ." PASS" ELSE ." FAIL" THEN` prints BOTH strings — in interpretation
\ state `."` emits immediately and the compiled branch tokens are never executed (nothing is
\ running them). Every branch check must live inside a colon definition, or the test proves nothing.
CREATE FLAG 0 ,
CREATE OTHER 0 ,

: T      ( f -- )  IF ." PASS" 10 EMIT EXIT THEN ." FAIL" 10 EMIT ;
: SPINN  ( n -- )  BEGIN 1- DUP 0= UNTIL ;        \ N iterations, no host involvement
: SPINF  ( -- )    BEGIN FLAG @ UNTIL ;           \ the doc's `: SPIN BEGIN FLAG @ UNTIL ;`
: SETFLAG ( -- )   -1 FLAG ! ;
: B7     ( f -- )  0= IF 0 OTHER ! 75 EMIT THEN ; \ P33's repro: branch body stores to a CREATE'd cell
: E1A    5 SPINN 0 = T ;
: E1B    2000 SPINN 0 = T ;
: E1D    0 B7 OTHER @ 0= T ;

." e1-loopcount5 " E1A
." e1-spin2000   " E1B
." e1-branchstore " E1D
." e1-preset-set " SETFLAG
." e1-preset-spin " SPINF ." PASS" 10 EMIT
