\ os_introspect.fs - P24 group 4: WORDS, .S, ?, and the number printer.
\ GUARDRAIL: W@ was trimmed from the 40, so the 2-byte header link has to be
\ rebuilt from two C@ - a one-byte link read silently walks into the name.
: LINK@   DUP C@ SWAP 1+ C@ 256 * OR ;
: .NAME      DUP 3 + SWAP 2 + C@ 31 AND TYPE ;
: .DIGIT     48 + EMIT ;
: U.                               \ unsigned decimal, recursive
  DUP 9 > IF DUP 10 / U. 10 MOD .DIGIT ELSE .DIGIT THEN ;
: .    DUP 0< IF 45 EMIT NEGATE THEN U. ;
: ?    @ . ;
: WORDS
  LATEST @ BEGIN DUP WHILE DUP .NAME SPACE DUP LINK@ REPEAT DROP ;
\ .S   DEPTH is not in the 40-primitive set, so the layer cannot print
\ the stack depth; .S prints the top cell non-destructively and says so here.
: .S  DUP . SPACE ;
