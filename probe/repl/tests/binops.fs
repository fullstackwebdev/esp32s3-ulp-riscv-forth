\ BINOPS — the ten same-shape binary primitives that P54 routes through one table.
\ Runs against artifacts/host_binops (-DP54_BINOPS=10). At rungs 1 and 5 the untouched words use P31's
\ bodies; the expected output must be IDENTICAL at every rung, which is what makes this file a check on the
\ generated subset list (a missing P_HAVE_* turns a word into `?`) as well as on the kernel.
\
\ GUARDRAIL: tests/suite.fs covers `+ - *` only — 8 of the 10 primitives P54 touches were untested, so a
\ kernel that computed `AND` as `OR` would have passed the whole suite. Every op is pinned here with the
\ cases where the tempting simplification breaks: signed vs unsigned compare, the `& 31` shift mask (RISC-V
\ masks shifts itself, C does not), and 32-bit wraparound in + and *.
\
\ GUARDRAIL: no `DO…LOOP`, no `R@`, no `ALLOT` (bench/README.md's dialect rules); and `.` prints no
\ separator, so the golden file is one concatenated run of decimal values.
\ GUARDRAIL: the 32-bit overflow case is written as `-2147483647 2 -` (wraps to 2147483647) and NOT as
\ `2147483647 1 + .`, because the prelude's `.` cannot print INT_MIN: it negates the value first and
\ -2147483648 stays negative, so the digit loop divides a negative number and emits the byte soup
\ `-./,),(`. Measured on the BASE build too, so it is a prelude limitation rather than anything P54
\ touches — the wrap itself is still pinned (`+` DROPped, `-` printed).
2 3 + .
-5 3 + .
2147483647 2147483647 + .
-2147483647 2 - .
7 3 - .
3 7 - .
0 1 - .
6 7 * .
-3 4 * .
65536 65536 * .
12 10 AND .
-1 0 AND .
12 10 OR .
-1 0 OR .
12 10 XOR .
5 5 XOR .
1 4 LSHIFT .
1 32 LSHIFT .
-1 0 LSHIFT .
16 2 RSHIFT .
-1 1 RSHIFT .
3 5 < .
5 3 < .
-1 0 < .
0 -1 < .
0 -1 U< .
-1 0 U< .
3 5 U< .
\ the converted words must still work from inside a colon definition (DOCOL/DOVAR/DOCON are not converted,
\ but they share the P31_SUBSET mechanism, so a subset list that forgot them fails HERE, not at load time)
: T 3 + ;
4 T .
: TP 4 LSHIFT 1 - ;
1 TP .
: TAND AND ;
12 10 TAND .
\ the stack effect must be exactly ( a b -- c ): four values consumed, four pushed, nothing net left behind
1 2 + 3 + 4 + .
