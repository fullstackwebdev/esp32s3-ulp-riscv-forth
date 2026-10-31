\ capacity_fill.fs — fixture: put tab[i] = i into data block 4, the deterministic input phases B and C scan.
\ GUARDRAIL: fetch the window ONCE and keep the pointer in a cell. `DATABLK BLOCK` inside the loop re-reads the
\ store on every iteration, so each C! is undone by the next fetch - measured as a window of filler and a sum of
\ 11712 instead of 8128, and then misread as a bug in the phase that merely reported the wrong data honestly.
4 CONSTANT DATABLK
CREATE fw 0 ,
: F0 ( -- ) DATABLK BLOCK fw ! ;
: FILLI ( -- ) F0 0 BEGIN DUP 128 < WHILE DUP DUP fw @ + C! 1 + REPEAT DROP ;
FILLI UPDATE
SAVE DROP
