\ test_far.fs — P34's six execution cases, all through the shadowed @ ! C@ C!.
\ GUARDRAIL: the far literals are built by FAR ( blk off -- fa ), never typed as 5-digit decimals —
\ a mistyped 0x8000_0000 expression is indistinguishable from a working far address in the output.
: T ( n -- ) . SP ;               \ print a result
: B ( blk off -- fa ) FAR ;

." == 0. proof: pre-existing words keep the raw primitive == " CR
CREATE EXITT 0 ,
' EXIT EXITT !
: TOK ( xt -- t ) 2 + RAW@ 65535 AND ;
: POST@ ( a -- x ) @ ;            \ compiled AFTER the shadow: must hold the pager's xt
." tok PRE@ = " ' PRE@ TOK T
." tok RAW@ = " ' RAW@ TOK T
." tok POST@ = " ' POST@ TOK T
." xt of @ now = " ' @ T
." PRE@ calls raw @ ? " ' PRE@ TOK ' RAW@ TOK = 0= IF 48 EMIT ELSE 49 EMIT THEN CR

." == 1. far read returns the server's bytes ==" CR
2 5 B @ T                         \ block 2 byte 5 = 5 + 7*2 = 19
." expect 19" CR
." transfers " FXFERS @ T CR

." == 2. far write then far read of the same cell ==" CR
42 3 9 B !                        \ write-through: 1 transfer
." transfers " FXFERS @ T CR
1 0 B @ DROP                      \ evict block 3: forces a real re-read from the server
." transfers " FXFERS @ T CR
3 9 B @ T                         \ 42 only if the server really kept it
." transfers " FXFERS @ T CR

." == 3. two far blocks alternating, and the cost ==" CR
FXFERS @
2 0 B @ DROP
1 0 B @ DROP
2 0 B @ DROP
1 0 B @ DROP
FXFERS @ SWAP - T                \ 4: every switch is a transfer
." expect 4" CR

." == 4. no answer: the line aborts with a name, no value ==" CR
9 0 B @                          \ block 9 is a black hole: the server never answers
." <-- no value above; " FERR @ T ." is ERR_NO_SERVER" CR

." == 5. a second request while one is outstanding is refused ==" CR
0 0 B @                          \ far_out is still set from the timeout
." <-- refused; " FERR @ T ." is ERR_BUSY" CR
FAR-RESET
0 0 B @ T ." back to work" CR

." == 6. a resident @ in a loop is not slowed by the wrapper ==" CR
." tok of the pre-shadow loop body  " ' PRE@ TOK T CR
." tok of the post-shadow loop body " ' POST@ TOK T CR
." FBLK " FBLK @ T ." FERR " FERR @ T CR
