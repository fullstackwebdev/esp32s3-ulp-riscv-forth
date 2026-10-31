
\ flagship E: read BLOCK 13 back, recompute 2*i, count mismatches. 0 is the paged round trip.
: RUNE ( -- ) XFM BLOCK vb3 ! 0 vb1 ! 0 vb4 !
  BEGIN vb1 @ 128 < WHILE
    vb1 @ 2 * vb1 @ vb3 @ + C@ = 0= IF vb4 @ 1 + vb4 ! THEN
    vb1 @ 1 + vb1 ! REPEAT
  vb4 @ . ;
RUNE
