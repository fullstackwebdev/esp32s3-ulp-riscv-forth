: SQ ( n -- n*n ) DUP * ;
: T1 ( -- ) 7 SQ 49 = IF 79 EMIT ELSE 88 EMIT THEN ;
: T2 ( -- ) 0 1 BEGIN DUP 5 < WHILE DUP EMIT 48 + 1+ ... ;
