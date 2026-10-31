\ DEPTH — the deepest legal recursion, and the refusal when it is exceeded.
\ Each level holds one data cell and one return cell, so SD=16 allows about 13 levels.
\ GUARDRAIL: expected output ends with ERR_STACK; the final 888 is the abort sentinel (unreachable).
: RX DUP 0= IF ELSE 1- RX THEN ;
\ GUARDRAIL: 15 is the deepest legal level and 16 is the first illegal one, measured - not guessed. Both
\ boundaries are in the workload so a change in SD or in the push accounting moves BOTH numbers and the
\ diff shows it. 888 must NOT appear: 16 RX sets errf and aborts the load.
15 RX .
16 RX .
888 .
