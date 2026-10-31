
\ flagship C: verify B's histogram out of BLOCK 12: bucket 0, total, largest bucket.
: > ( a b -- a>b ) SWAP < ;
: CVSCAN ( -- ) HISTBLK BLOCK vb3 ! 0 vb1 ! 0 vb4 ! 0 vb5 !
  BEGIN vb1 @ 16 < WHILE
    vb1 @ vb3 @ + C@ vb4 @ + vb4 !
    vb1 @ vb3 @ + C@ vb5 @ > IF vb1 @ vb3 @ + C@ vb5 ! THEN
    vb1 @ 0 = IF vb1 @ vb3 @ + C@ vb2 ! THEN
    vb1 @ 1 + vb1 ! REPEAT ;
: RUNC ( -- ) CVSCAN vb2 @ . vb4 @ . vb5 @ . ;
RUNC
