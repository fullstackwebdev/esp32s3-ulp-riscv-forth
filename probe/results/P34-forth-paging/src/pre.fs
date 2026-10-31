\ pre.fs — compiled against the RAW primitives, before anything is shadowed.
\
\ GUARDRAIL: every word here is written before paging.fs redefines @ ! C@ C!, so its body holds the
\ xt of the primitive that existed at compile time. RAW@/RAW!/RAWC@/RAWC! are the same primitives
\ under explicit names — they are what makes the shadowing proof readable, and they are what the
\ paging words themselves use on dictionary variables (a dictionary read must never page).
\ GUARDRAIL: this engine has no `.`, `=`, `+!`, `SP` or `CR` (P32's D = C + I J UNLOOP GPIO!
\ ' CONSTANT ( ." (.")) — so the test harness spells them in Forth rather than adding primitives,
\ which would price a machine nobody is buying.

: = ( a b -- f ) - 0= ;
: +! ( n a -- ) DUP @ ROT + SWAP ! ;
: SP ( -- ) 32 EMIT ;
: CR ( -- ) 10 EMIT ;

: . ( n -- )                      \ print signed decimal, no recursion (no name visible to itself)
  DUP 0 < IF 45 EMIT 0 SWAP - THEN
  DUP 0= IF 48 EMIT DROP EXIT THEN
  0 SWAP                          ( cnt val )
  \ GUARDRAIL: no `<>` in this primitive set (only 0= and <) — WHILE already means "nonzero",
  \ so the test is `DUP WHILE`, not `DUP 0 <> WHILE`, which finds an undefined word.
  BEGIN DUP WHILE 10 /MOD SWAP >R SWAP 1 + SWAP REPEAT DROP
  BEGIN DUP WHILE 48 R> + EMIT 1 - REPEAT DROP ;

: RAW@ ( a -- x ) @ ;
: RAW! ( x a -- ) ! ;
: RAWC@ ( a -- c ) C@ ;
: RAWC! ( c a -- ) C! ;

\ PRE@ and PRE! are the "pre-existing word" of the probe: compiled while @ is still the primitive.
: PRE@ ( a -- x ) @ ;
: PRE! ( x a -- ) ! ;
