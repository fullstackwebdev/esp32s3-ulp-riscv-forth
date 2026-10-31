\ flagship phase C: verify phase B's histogram out of the store: bucket 0, total, largest bucket.
12 CONSTANT HISTBLK
CREATE hw 0 , CREATE ci 0 , CREATE tot 0 , CREATE b0 0 , CREATE mx 0 ,
: > ( a b -- a>b ) SWAP < ;
: HIST ( -- addr ) hw @ ;
: SCAN ( -- ) HISTBLK BLOCK hw ! 0 ci ! 0 tot ! 0 mx !
  BEGIN ci @ 16 < WHILE
    ci @ HIST + C@ tot @ + tot !
    ci @ HIST + C@ mx @ > IF ci @ HIST + C@ mx ! THEN
    ci @ 0 = IF ci @ HIST + C@ b0 ! THEN
    ci @ 1 + ci ! REPEAT ;
: RUNV ( -- ) SCAN b0 @ . tot @ . mx @ . ;
RUNV
