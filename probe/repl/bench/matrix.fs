\ MATRIX — 2x2 multiply, 500 times: [[1,2],[3,4]] x [[5,6],[7,8]] = [[19,22],[43,50]].
\ Eight multiplies and six adds per iteration, all on the data stack (no variables).
\ Expected: trace 19+22+43+50 = 134 per iteration, so 500 x 134 = 67000.
\ GUARDRAIL: one colon word per matrix entry. Writing all eight products in ONE word put more than 16
\ values live before the reduction and the run died with ERR_STACK — on this machine a wide expression is
\ a stack-depth bug, not just a long line.
: A11 1 5 * 2 7 * + ;
: A12 1 6 * 2 8 * + ;
: A21 3 5 * 4 7 * + ;
: A22 3 6 * 4 8 * + ;
: TRACE A11 A12 + A21 + A22 + ;
: MAT 0 500 BEGIN SWAP TRACE + SWAP 1- DUP 0= UNTIL DROP . ;
MAT
