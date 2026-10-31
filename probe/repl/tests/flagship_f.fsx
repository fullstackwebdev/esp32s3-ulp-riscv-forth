
\ flagship F: report the histogram from BLOCK 12 with 3-digit padding.
: PAD3 ( n -- ) DUP 100 < IF 48 EMIT THEN DUP 10 < IF 48 EMIT THEN . 32 EMIT ;
: RUNF ( -- ) HISTBLK BLOCK vb3 ! 0 vb1 !
  BEGIN vb1 @ 16 < WHILE vb1 @ vb3 @ + C@ PAD3 vb1 @ 1 + vb1 ! REPEAT ;
RUNF
