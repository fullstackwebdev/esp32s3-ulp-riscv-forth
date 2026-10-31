\ capacity_a.fsx — phase A of the capacity test. tools/mkcapacity.py seeds this text into blocks and the
\ generated tests/overlay_capacity.fs loads it through the block store; it is not compiled by the suite directly.
\
\ Job: fill the data window from an LCG, then accumulate sum, sum of squares, an XOR fold, min and max using
\ one plain loop per statistic (variables, no stack juggling - the point of this phase is to be BIG and
\ obviously correct, and every number it prints is re-derived in Python for the expected transcript).
\ The last line RUNS the phase: with the deferred source switch a phase's text executes when the interpreter
\ next asks for a token, so a phase runs itself at the end of its own block.
4 CONSTANT DATABLK
CREATE seed 7 ,
CREATE sum 0 ,
CREATE ss 0 ,
CREATE xo 0 ,
CREATE lo 255 ,
CREATE hi 0 ,
CREATE idx 0 ,
CREATE tw 0 ,
: TAB ( -- addr ) tw @ ;
: FETCH ( -- ) DATABLK BLOCK tw ! ;   \ ONE fetch: TAB must not re-read the store, or every
                                      \ write is undone by the next call and the statistics run on
                                      \ the store's old contents (measured: sum 1171 for 0..127)
: > ( a b -- a>b ) SWAP < ;
: NEXT ( -- b ) seed @ 1777 * 1234 + 251 /MOD DROP DUP seed ! ;
: NEXTI ( -- b ) seed @ 1 + 128 /MOD DROP DUP seed ! ;   \ 0,1,2,... cyclical: checkable by hand
: FILL ( -- ) FETCH
  0 idx ! BEGIN idx @ 128 < WHILE NEXTI idx @ TAB + C! idx @ 1 + idx ! REPEAT UPDATE SAVE DROP ;
: DOSUM ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE idx @ TAB + C@ sum @ + sum ! idx @ 1 + idx ! REPEAT ;
: DOSS ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE idx @ TAB + C@ DUP * ss @ + ss ! idx @ 1 + idx ! REPEAT ;
: DOXO ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE idx @ TAB + C@ xo @ XOR xo ! idx @ 1 + idx ! REPEAT ;
: DOMIN ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE idx @ TAB + C@ lo @ < IF idx @ TAB + C@ lo ! THEN idx @ 1 + idx ! REPEAT ;
: DOMAX ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE idx @ TAB + C@ hi @ > IF idx @ TAB + C@ hi ! THEN idx @ 1 + idx ! REPEAT ;
: RUNFILL ( -- ) FILL DOSUM DOSS DOXO DOMIN DOMAX sum @ . ss @ . xo @ . lo @ . hi @ . ;
RUNFILL
