\ Shipping-engine regression suite. Runs on the HOST build of src/uforth.c.
\ Every line prints a value with '.'; tests/expected.txt is the golden output.
\ GUARDRAIL: this file must only use words that exist in the baked image (prelude + primitives).
2 3 + .
7 3 - .
6 7 * .
1 2 3 + + .
0 1 2 3 4 5 + + + + + .
-5 .
-5 3 + .
123456 .
7 DUP * .
5 DUP + .
9 4 - 2 * .
: SQ DUP * ;
7 SQ .
: CUBE DUP DUP * * ;
3 CUBE .
: DOUBLE 2 * ;
21 DOUBLE .
1 1 1 1 1 NIP .
5 5 = .
5 6 = .
5 5 <> .
: ABS DUP 0 < IF NIP NIP 0 ELSE THEN ;
-7 ABS .
: TOCNT 5 BEGIN 1- DUP 0 = UNTIL DROP ;
TOCNT .
HERE .
LATEST 0 <> .
