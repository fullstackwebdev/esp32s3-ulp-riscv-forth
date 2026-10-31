\ corpus_extra.fs - P02 corpus on top of boot_min.fs.
\
\ Chosen to be representative rather than kind: one ~18-token word (MIX), one
\ word with three string literals (BANNER), branch-heavy words (CLAMP, LED),
\ a counted loop, and indefinite loops. Every unit is a plain colon
\ definition, because the page rule ("one definition per page") is a rule
\ about colon definitions.

: SUMN   0 SWAP 0 DO I + LOOP ;
: STARS  5 0 DO 42 EMIT LOOP ;
: BANNER ." boot" ." ok" ." done" ;
: PROMPT ." name? " KEY DROP ;
: CLAMP  DUP 0 < IF DROP 0 ELSE DUP 1000 > IF DROP 1000 THEN THEN ;
: LED    DUP GPIO@ IF 1 ELSE 0 THEN SWAP GPIO! ;
: BLINK  10 0 DO 1 I GPIO! 5 MS LOOP ;
: MENU   BEGIN KEY DUP 13 = UNTIL DROP ;
: MIX    DUP 0= SWAP 0< OR IF DROP DROP
         ELSE OVER 1+ >R SWAP 1+ R> SWAP DROP THEN ;
: SPIN   BEGIN DUP 0> WHILE 1- 5 MS REPEAT DROP ;
