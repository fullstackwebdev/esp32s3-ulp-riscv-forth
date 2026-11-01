: G2 ( n -- ) DUP 2 = IF DROP 45 EMIT EXIT THEN DROP 92 EMIT ;
: G1 ( n -- ) DUP 0= IF DROP 124 EMIT EXIT THEN DUP 1 = IF DROP 47 EMIT EXIT THEN G2 ;
: STEP ( -- ) PA @ 1+ PA ! ;
: SPIN3 ( -- ) 11 2 AT ." step " PA @ 4 /MOD DROP G1 SP PA @ .N SENT ;
: GAUGE3 ( -- ) STEP SPIN3 15 2 AT ." phases done: " PA @ .N SENT 0 CHAIN ;
