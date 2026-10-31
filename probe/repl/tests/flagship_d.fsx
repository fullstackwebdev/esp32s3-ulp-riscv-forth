
\ flagship D: write a derived block (2*i mod 256) into BLOCK 13 - the cheap shape of a paged write.
: RUND ( -- ) XFM BLOCK vb3 ! 0 vb1 !
  BEGIN vb1 @ 128 < WHILE vb1 @ 2 * vb1 @ vb3 @ + C! vb1 @ 1 + vb1 ! REPEAT
  UPDATE SAVE DROP ;
RUND
