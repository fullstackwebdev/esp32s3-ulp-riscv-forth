\ capacity_b.fsx — scans 1-6
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
CREATE z1 0 ,
CREATE z2 0 ,
CREATE z3 0 ,
CREATE z4 0 ,
CREATE z5 0 ,
CREATE z6 0 ,
: TAB ( -- addr ) tw @ ;
: FETCH ( -- ) DATABLK BLOCK tw ! ;
: > ( a b -- a>b ) SWAP < ;
: NX ( -- ) idx @ 1 + idx ! ;
: B1 ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ z1 @ + z1 ! NX REPEAT ;
: B2 ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ 0= IF z2 @ 1 + z2 ! THEN NX REPEAT ;
: B3 ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ 63 > IF z3 @ 1 + z3 ! THEN NX REPEAT ;
: B4 ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ 2 /MOD DROP 0= IF z4 @ 1 + z4 ! THEN NX REPEAT ;
: B5 ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ 2 /MOD DROP 0= 0= IF z5 @ 1 + z5 ! THEN NX REPEAT ;
: B6 ( -- ) 0 idx ! BEGIN idx @ 128 < WHILE
    idx @ TAB + C@ DUP * z6 @ + z6 ! NX REPEAT ;
: SHOW ( -- ) z1 @ . z2 @ . z3 @ . z4 @ . z5 @ . z6 @ . ;
: REPORT ( -- ) FETCH B1 B2 B3 B4 B5 B6 SHOW ;
REPORT
