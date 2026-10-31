\ os_introspect.fs - P26 group 4: WORDS and .S only. ? is dropped.
\ GUARDRAIL: W@ was trimmed from the 40, so the 2-byte header link is
\ rebuilt from two C@ inside WORDS; a one-byte link read silently walks
\ into the name and WORDS prints garbage. .NAME/LINK@ are inlined: each
\ costs 4 B of code field and 4 B of call token, and each has one caller.
: WORDS
  LATEST @ BEGIN DUP WHILE
    2 + DUP C@ 31 AND SWAP 1+ SWAP TYPE 32 EMIT
    DUP C@ SWAP 1+ C@ 256 * OR
  REPEAT DROP ;
\ U. is required before .S can say anything true: the 40 has no . / U. /
\ .R primitive, so a decimal printer is layer content, not glaze.
: U.   DUP 9 > IF DUP 10 / U. 10 MOD THEN 48 + EMIT ;
\ GUARDRAIL: DEPTH is not in the 40-primitive set, so .S cannot walk the
\ stack - it prints the top cell non-destructively and says so, instead of
\ printing a fake depth.
: .S   U. 32 EMIT ;
