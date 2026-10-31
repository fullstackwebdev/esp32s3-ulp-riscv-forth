\ Regression: deep recursion must FAIL LOUDLY, not wrap the stack (F-115).
\ At SD=16 the 17th push used to land in slot 0: `15 FIB .` answered 377 instead of 610, and a
\ three-line file hung the machine. The suite never caught it because it peaks at 6 cells.
\ GUARDRAIL: the final 888 is unreachable BY DESIGN — ERR_STACK sets errf, which aborts the load.
\ It is the sentinel that proves the abort: if the bug returns, 888 appears and this test fails.
: FIB DUP 2 < IF ELSE DUP 1- FIB SWAP 2 - FIB + THEN ;
10 FIB .
15 FIB .
888 .
