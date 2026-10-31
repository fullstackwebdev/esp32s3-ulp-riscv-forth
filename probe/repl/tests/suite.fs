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
\ GUARDRAIL: no DROP. TOCNT used to end in DROP, so it left NOTHING on the stack and the following `.`
\ popped an empty stack — sp wrapped to 255, the session was corrupt from that line on, and the next
\ assertion (`HERE .`) was printing garbage that happened to be stable. A test whose value comes from an
\ underflowed stack cannot fail meaningfully. Leaving the loop's final 0 makes `.` print a real 0.
: TOCNT 5 BEGIN 1- DUP 0 = UNTIL ;
TOCNT .
\ GUARDRAIL: this used to be a bare `HERE .` — an ABSOLUTE address that moved whenever DICT or PAD moved
\ (P59's 2-byte compaction broke it by exactly 2) and that certified nothing about the machine. What is worth
\ pinning is that a definition can be created and then EXECUTED: define SZ and call it. The value is
\ invariant to any layout change, and it fails if `:`/`;` or the call path breaks.
: SZ 7 ; SZ .
LATEST 0 <> .
