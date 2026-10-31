\ capacity_c.fsx — scans 7-12
\ Splits phase B so each half fits the sealed free space; every scan is the proven loop shape.
\ capacity_b.fsx — phase B of the capacity test: twelve independent scans over the same data window.
\ Every scan is the ONE loop shape that is already proven here (initialise a cell, step an index, accumulate),
\ because the earlier version's array-indexed histogram and longest-run scan were where the bugs lived: each
\ word was right alone and wrong in sequence. It runs itself on its last line.
\ With tab[i] = i the answers are: sum 8128, zeros 1, >63 64, even 64, odd 64, sumsq 690880, /3 43, /5 26,
\ ==127 1, <64 64, sum of even indices 4032, max 127. Re-derived independently in Python for the expected file.
4 CONSTANT DATABLK
CREATE tw 0 ,
CREATE idx 0 ,
CREATE z7 0 ,
CREATE z8 0 ,
CREATE z9 0 ,
CREATE z10 0 ,
CREATE z11 0 ,
CREATE z12 0 ,
: TAB ( -- addr ) tw @ ;
: FETCH ( -- ) DATABLK BLOCK tw ! ;
: > ( a b -- a>b ) SWAP < ;
: NX ( -- ) idx @ 1 + idx ! ;
: B7 ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ 3 /MOD DROP 0= IF z7 @ 1 + z7 ! THEN NX REPEAT ;
: B8 ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ 5 /MOD DROP 0= IF z8 @ 1 + z8 ! THEN NX REPEAT ;
: B9 ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ 127 = IF z9 @ 1 + z9 ! THEN NX REPEAT ;
: B10 ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ 64 < IF z10 @ 1 + z10 ! THEN NX REPEAT ;
: B11 ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE
    idx @ 2 /MOD DROP 0= IF idx @ TAB + C@ z11 @ + z11 ! THEN NX REPEAT ;
: B12 ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ z12 @ > IF idx @ TAB + C@ z12 ! THEN NX REPEAT ;
: SHOW ( -- ) z7 @ . z8 @ . z9 @ . z10 @ . z11 @ . z12 @ . ;
: REPORT ( -- ) FETCH B7 B8 B9 B10 B11 B12 SHOW ;
REPORT
