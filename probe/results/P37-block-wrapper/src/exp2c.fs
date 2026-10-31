: P  ( f -- ) IF 65 EMIT ELSE 66 EMIT THEN ;
: A7 ( -- ) BLK-ABORT 15 BLOCK DUP 0 < P DUP -3 = P BLKERR @ -3 = P 10 EMIT ;
." dup-neg-exact-err " A7
