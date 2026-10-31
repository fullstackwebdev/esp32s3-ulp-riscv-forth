\ flagship phase B: 16-bucket histogram of the data window.
\ GUARDRAIL: ONE WINDOW, ONE BLOCK. The first version fetched the data block and the histogram block and kept both
\ addresses; the second fetch overwrote the window, so DATA pointed at the histogram and the tally was nonsense
\ (measured: buckets summing to 44 instead of 128). The correct pattern is always: read the source/window, compute
\ into PHASE-LOCAL CELLS, then fetch the destination block, write it, SAVE.
4 CONSTANT DATABLK
12 CONSTANT HISTBLK
CREATE dw 0 ,
CREATE h 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 ,
CREATE bi 0 ,
: DATA ( -- addr ) dw @ ;
: HP ( n -- addr ) 4 * h + ;
: ZERO ( -- ) 0 bi ! BEGIN bi @ 16 < WHILE 0 bi @ HP ! bi @ 1 + bi ! REPEAT ;
: TALLY ( -- ) 0 bi ! BEGIN bi @ 128 < WHILE
    bi @ DATA + C@ 3 RSHIFT DUP HP @ 1 + SWAP HP !
    bi @ 1 + bi ! REPEAT ;
: PUBLISH ( -- ) 0 bi ! HISTBLK BLOCK
  BEGIN bi @ 16 < WHILE bi @ HP @ bi @ 4 *   h + SWAP  0 bi @ HP @ bi @ + C! bi @ 1 + bi ! REPEAT ;
: RUNH ( -- ) DATABLK BLOCK dw ! ZERO TALLY  0 bi ! HISTBLK BLOCK
  BEGIN bi @ 16 < WHILE bi @ HP @ bi @  0 + + C! bi @ 1 + bi ! REPEAT
  UPDATE SAVE DROP ;
RUNH
