( Keys and the open path. A phase cannot see another phase's words, so this carries its own WAIT and SLOT. )
: WAIT ( -- c ) BEGIN KEY DUP -1 = WHILE DROP REPEAT ;
: SLOT ( -- i ) SHELF_ST 4 + @ 3 * SHELF_ST @ + ;
: KDN ( c -- ) 106 = IF SHELF_ST @ 1+ 3 /MOD DROP SHELF_ST ! THEN ;
: KUP ( c -- ) 107 = IF SHELF_ST @ 2 + 3 /MOD DROP SHELF_ST ! THEN ;
: KHL ( c -- ) DUP 108 = OVER 104 = OR IF SHELF_ST 4 + DUP @ 1 XOR SWAP ! THEN DROP ;
: KENT ( c -- ) 13 = IF SLOT DUP IF 1+ THEN 1+ 8 * DUP APP ! 0 APP_PG ! CHAIN THEN ;
: KEYDO ( c -- ) DUP KDN DUP KUP DUP KHL KENT ;
: SHELF-KEYS ( -- ) WAIT KEYDO NXT @ 0= IF 56 CHAIN THEN ;
