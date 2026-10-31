\ paging.fs — P34: R5's transparency, written in Forth.
\
\ far = 0x80000000 + block*512 + offset.  Bit 31 set => far address.  ONE C primitive exists:
\   FAR-XFER ( op block -- buf st )   op 0 = fetch block into far_buf, 1 = send far_buf as block,
\                                     2 = drop an unanswered request.  buf = far_buf's Forth address.
\ Everything below is Forth. Nothing below is C.
\
\ GUARDRAIL: these words use RAW@/RAW!/RAWC@/RAWC! for dictionary and buffer access. If they used
\ @/! they would compile the *shadow* and each residency test would re-enter the pager — infinite
\ recursion the engine reports as a stack overflow, not as a wrong answer.
\ GUARDRAIL: FAR-XFER pushes the buffer's Forth address, so no file here spells 908. A literal
\ address would silently point into the dictionary the day MEMSZ moves (P33's lesson).

-2 CONSTANT ERR_BUSY
-3 CONSTANT ERR_NO_SERVER
-4 CONSTANT ERR_CRC

2147483647 CONSTANT FAMASK        \ bit 31 is the far flag, the rest is block*512+offset
512 CONSTANT FABSZ

CREATE FBLK -1 ,                  \ block currently in far_buf; -1 = none
CREATE FBLKN 0 ,                  \ block the last request asked for
CREATE FBUF 0 ,                   \ far_buf's Forth address, as FAR-XFER handed it over
CREATE FERR 0 ,                   \ 0 = last far access worked, else its named code
CREATE FXFERS 0 ,                 \ transfers performed: a thrashing program is measurable
CREATE FHERE 0 ,                  \ FAR-ALLOT's next free far offset

: FAR? ( a -- f ) 0 < ;           \ bit 31 set reads as negative
: F>BLK ( fa -- blk ) FAMASK AND FABSZ /MOD DROP ;
: F>OFF ( fa -- off ) FAMASK AND 511 AND ;
: FAR ( blk off -- fa ) SWAP FABSZ * + 2147483647 1 + + ;

: FAR-FAIL ( st -- )              \ the only way a far access may fail: named, never a value
  DUP FERR !
  DUP ERR_BUSY =      IF DROP ." ERR_BUSY " EXIT THEN
  DUP ERR_NO_SERVER = IF DROP ." ERR_NO_SERVER " EXIT THEN
  DUP ERR_CRC =       IF DROP ." ERR_CRC " EXIT THEN
  DROP ." ERR_UNNAMED " ;

: FAR-READ ( blk -- st )          \ make blk resident; 0 = resident, else the code (FBLK unchanged)
  DUP FBLK @ = IF DROP 0 EXIT THEN
  DUP FBLKN !
  0 SWAP FAR-XFER                 ( buf st )
  SWAP FBUF !                     ( st )
  DUP 0= IF FBLKN @ FBLK ! FXFERS @ 1 + FXFERS ! THEN ;

: FAR-SAVE ( -- st )              \ send the resident block back (op 1)
  FBLK @ DUP 0 < IF DROP 0 EXIT THEN
  1 SWAP FAR-XFER                 ( buf st )
  SWAP DROP
  DUP 0= IF FXFERS @ 1 + FXFERS ! THEN ;

: FAR-RESET ( -- ) 2 0 FAR-XFER SWAP DROP DROP 0 FERR ! ;

: FAR-ALLOT ( n -- fa )           \ hand out n bytes of far space (4-byte aligned)
  FHERE @ DUP >R + 3 + -4 AND FHERE !
  R> 2147483647 1 + + ;

\ GUARDRAIL: inside the four shadows every dictionary read is RAW@ — `FBUF @` there
\ would find the new @ (its header exists from the moment `:` runs) and recurse instead of reading
\ the buffer base. The helper words above are safe: they were compiled before the shadow existed.
\ ---- the shadowing: from here on, @ ! C@ C! page ----
\ GUARDRAIL: these four words are defined AFTER the prelude, so every word already compiled keeps
\ the raw primitive's xt and pays nothing; only words compiled from here on see the shadow. That
\ asymmetry is the whole mechanism and it is a property of token threading, not of a C table.: @ ( a -- x )
  DUP FAR? IF
    DUP F>BLK FAR-READ            ( fa st )
    IF SWAP DROP FAR-FAIL EXIT THEN
    F>OFF FBUF RAW@ + RAW@
  ELSE RAW@ THEN ;

: ! ( x a -- )
  DUP FAR? IF
    DUP F>BLK FAR-READ            ( x fa st )
    IF SWAP DROP SWAP DROP FAR-FAIL EXIT THEN
    F>OFF FBUF RAW@ + RAW!
    FAR-SAVE IF FAR-FAIL THEN
  ELSE RAW! THEN ;

: C@ ( a -- c )
  DUP FAR? IF
    DUP F>BLK FAR-READ
    IF SWAP DROP FAR-FAIL EXIT THEN
    F>OFF FBUF RAW@ + RAWC@
  ELSE RAWC@ THEN ;

: C! ( c a -- )
  DUP FAR? IF
    DUP F>BLK FAR-READ
    IF SWAP DROP SWAP DROP FAR-FAIL EXIT THEN
    F>OFF FBUF RAW@ + RAWC!
    FAR-SAVE IF FAR-FAIL THEN
  ELSE RAWC! THEN ;
