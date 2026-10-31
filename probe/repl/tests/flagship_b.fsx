\ flagship B: 16-bucket histogram into BLOCK 12, cells are resident (vb1..vb5 from flagship_common.fs).
\ GUARDRAIL: ONE WINDOW, ONE BLOCK - read the source, tally into cells, then fetch the destination, write, SAVE.
\ GUARDRAIL: UPDATE alone does not persist; the store keeps its old bytes (measured: all zeros).
CREATE hb 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 ,
: HP ( n -- addr ) 4 * hb + ;
: HTZERO ( -- ) 0 vb1 ! BEGIN vb1 @ 16 < WHILE 0 vb1 @ HP ! vb1 @ 1 + vb1 ! REPEAT ;
: HTALLY ( -- ) 0 vb1 !
  BEGIN vb1 @ 128 < WHILE
    vb1 @ vb2 @ + C@ 3 RSHIFT DUP HP @ 1 + SWAP HP ! vb1 @ 1 + vb1 !
  REPEAT ;
: HTROWS ( -- ) HISTBLK BLOCK vb3 ! 0 vb1 !
  BEGIN vb1 @ 16 < WHILE vb1 @ HP @ vb1 @ vb3 @ + C! vb1 @ 1 + vb1 ! REPEAT
  UPDATE SAVE DROP ;
: RUNB ( -- ) DATABLK BLOCK vb2 ! HTZERO HTALLY HTROWS ;
RUNB
