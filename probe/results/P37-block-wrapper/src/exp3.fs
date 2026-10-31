\ exp3.fs - P37 experiment 3: the bound lives in Forth, where a program can see it.
\   host_blocks boot37.fs blocks.fs exp3.fs
\ BLOCKR polls BLKXFER at most POLLS times and then reports ERR_NO_SERVER. If the retry loop runs,
\ it reaches the named error. If the loop is broken, it hangs before ever reporting.
CREATE POLLS 0 ,
: BLOCKR ( n -- addr|st )
  DUP BLKN !
  4 POLLS !
  BEGIN
    0 BLKXFER DUP BLKERR !        \ the C bound (BLKWAIT) runs out inside this call
    0= IF DROP 0 BLKDRT ! EXIT THEN
    DROP
    POLLS @ 1- POLLS !
    POLLS @ 0=                    \ true = stop retrying: UNTIL jumps back on a 0
  UNTIL
  ERR_NO_SERVER DUP BLKERR ! ;
: T    ( f -- ) IF ." PASS" 10 EMIT EXIT THEN ." FAIL" 10 EMIT ;
: E3   ( -- )   15 BLOCKR -3 = BLKERR @ -3 = AND T ;
: E3B  ( -- )   0 BLOCKR 0 BLKDRT @ 0= AND 0= T ;
." e3-bounded-noserver " E3
." e3-server-answers   " E3B
