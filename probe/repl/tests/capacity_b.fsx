\ capacity_b.fsx — phase B of the capacity test: independent recount over the same window, a 16-bucket
\ histogram, parity counts, a threshold count and the longest ascending run. Same rules as phase A: it runs
\ itself on its last line, and every number is re-derived in Python for the expected transcript.
4 CONSTANT DATABLK
CREATE tw 0 ,
CREATE idx 0 ,
CREATE rsum 0 ,
CREATE evn 0 ,
CREATE odd 0 ,
CREATE below 0 ,
CREATE run 0 ,
CREATE best 0 ,
CREATE h 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 ,
: TAB ( -- addr ) tw @ ;
: FETCH ( -- ) DATABLK BLOCK tw ! ;
: HP ( n -- addr ) 4 * h + ;
: > ( a b -- a>b ) SWAP < ;
: RECOUNT ( -- ) 0 idx !
  BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ rsum @ + rsum !
    idx @ 1 + idx ! REPEAT ;
: HIST ( -- ) 0 idx !
  BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ 3 RSHIFT DUP HP @ 1 + SWAP HP !
    idx @ 1 + idx ! REPEAT ;
: PARITY ( -- ) 0 idx !
  BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ 2 /MOD DROP
    IF odd @ 1 + odd ! ELSE evn @ 1 + evn ! THEN
    idx @ 1 + idx ! REPEAT ;
: THRESH ( -- ) 0 idx !
  BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ 64 < IF below @ 1 + below ! THEN
    idx @ 1 + idx ! REPEAT ;
: RUNS ( -- ) 0 run ! 0 best ! 1 idx !
  BEGIN idx @ 128 < WHILE
    idx @ 1 - TAB + C@ idx @ TAB + C@ <
    IF run @ 1 + run ! ELSE 0 run ! THEN
    run @ best @ > IF run @ best ! THEN
    idx @ 1 + idx ! REPEAT ;
: DUMP ( -- ) 0 idx !
  BEGIN idx @ 16 < WHILE idx @ HP @ . idx @ 1 + idx ! REPEAT ;
: REPORT ( -- ) RECOUNT HIST PARITY THRESH RUNS rsum @ . DUMP evn @ . odd @ . below @ . best @ . ;
REPORT
