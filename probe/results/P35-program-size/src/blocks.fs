\ blocks.fs - P33: the visible block layer. Everything an operator sees is here; the
\ only C is BLKXFER ( n op -- addr st ), the mailbox handshake, which Forth cannot do.
\
\ A block is 512 B of a 2 KB file. Nothing is transparent: no frames, no page table, no
\ fault path. A word that wants block n says BLOCK n. That is the 1980s block file.
\
\ GUARDRAIL: a failed BLOCK returns its named code, never a buffer address and never a
\ zero-filled buffer. Checking BLKERR @ is the operator's job, exactly as checking the
\ result of a disk word was in 1980 — the layer refuses to make a wrong read look right.

-2 CONSTANT ERR_BUSY         \ a request is already outstanding (P16: only one, ever)
-3 CONSTANT ERR_NO_SERVER    \ nothing answered inside the bounded wait
-4 CONSTANT ERR_CRC          \ the checksum in the mailbox does not match the buffer

CREATE BLKN   0 ,            \ the block number BLOCK last requested
CREATE BLKERR 0 ,            \ 0 = the last request worked, else its code
CREATE BLKDRT  0 ,           \ -1 = the buffer was written to since BLOCK

: RAISE ( st -- )            \ name the failure; the code stays on the caller's stack
  DUP ERR_BUSY =      IF DROP ." ERR_BUSY " EXIT THEN
  DUP ERR_NO_SERVER = IF DROP ." ERR_NO_SERVER " EXIT THEN
  DUP ERR_CRC =       IF DROP ." ERR_CRC " EXIT THEN
  DROP ." ERR_UNNAMED " ;

: BLOCK ( n -- addr )        \ addr when BLKERR @ is 0, else the code: the buffer is untouched
  DUP BLKN !
  0 BLKXFER
  DUP BLKERR !
  0= IF 0 BLKDRT ! ELSE DUP RAISE SWAP DROP THEN ;

: UPDATE ( -- )              \ the buffer is dirty; SAVE will send it
  -1 BLKDRT ! ;

: SAVE ( -- st )             \ send the buffer back as block BLKN; 0 = written
  BLKDRT @ 0= IF 0 EXIT THEN
  BLKN @ 1 BLKXFER
  DUP BLKERR !
  0= IF DROP 0 BLKDRT ! 0 ELSE DUP RAISE SWAP DROP THEN ;

: BLK-ABORT ( -- )           \ drop an unanswered request instead of waiting for it forever
  0 2 BLKXFER DROP DROP 0 BLKERR ! ;
