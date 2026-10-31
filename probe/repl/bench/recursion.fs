\ RECURSION — fib(12) = 144. Exponential call pressure: 465 calls for one answer.
\ This is the worst case for the return stack and for call/return overhead.
: FIB DUP 2 < IF ELSE DUP 1- FIB SWAP 2 - FIB + THEN ;
12 FIB .
