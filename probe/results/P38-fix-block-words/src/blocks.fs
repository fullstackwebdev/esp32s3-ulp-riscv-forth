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
-5 CONSTANT ERR_RANGE        \ the block number cannot be a block of any file (negative)
-6 CONSTANT ERR_BUFOVER      \ the dictionary has grown into the block buffer (C: blk_place_ok)

CREATE BLKN   0 ,            \ the block number BLOCK last requested
CREATE BLKERR 0 ,            \ 0 = the last request worked, else its code
CREATE BLKDRT  0 ,           \ -1 = the buffer was written to since BLOCK

: RAISE ( st -- st )         \ name the failure; the code stays on the caller's stack
\ GUARDRAIL: no ELSE anywhere in this layer. On the host build an IF...ELSE...THEN word whose
\ branch body stores to a CREATE'd cell hangs the engine (measured, P33 artifacts/t*.fs), while
\ the same body under a bare IF runs. Until that is explained, a layer that must execute uses
\ IF ... EXIT THEN, which is also what a 1980s block file's words look like.
\ GUARDRAIL: P38 fix 2b — the old lines were `DUP ERR_BUSY = IF DROP ." ERR_BUSY " EXIT THEN`.
\ `=` is `- 0=`, so the DUP leaves ( st st ), `=` leaves ( st flag ) and IF pops the flag: the DROP
\ then removed the *code* this word promises to keep, and RAISE returned nothing. Without the DROP
\ the code is still there for the caller (and for BLOCK, which returns it).
  DUP ERR_BUSY =      IF ." ERR_BUSY " EXIT THEN
  DUP ERR_NO_SERVER = IF ." ERR_NO_SERVER " EXIT THEN
  DUP ERR_CRC =       IF ." ERR_CRC " EXIT THEN
  DUP ERR_RANGE =     IF ." ERR_RANGE " EXIT THEN
  DUP ERR_BUFOVER =   IF ." ERR_BUFOVER " EXIT THEN
  ." ERR_UNNAMED " ;

: BLOCK ( n -- addr | code )  \ addr when BLKERR @ is 0, else the named code: the buffer is untouched
\ GUARDRAIL: P38 fix 2a — this used to be `0= IF DROP 0 BLKDRT ! EXIT THEN`. BLKXFER leaves
\ ( addr st ) and `0=` is a TOS-only op (P_ZEQ pushes a flag and does not pop the address), so the
\ flag replaced st and the DROP threw away the buffer address BLOCK must return: on success BLOCK
\ returned nothing and the caller's `!` popped an empty stack (P37: sp wrapped to 255). DUP first,
\ so the IF sees ( addr st flag ) and the DROP removes only the status. The success path therefore
\ leaves exactly one address.
\ GUARDRAIL: a negative block number is not a block of *any* file, and the mailbox field is u32, so
\ sending it would ask the server about block 4294967295. Refuse locally, before the request: from
\ the layer's contract "a failed BLOCK returns its named code". The *upper* bound belongs to the
\ server (the file's size is not the client's to know): block 15 still answers -3, as P33 recorded.
  DUP 0 < IF DROP ERR_RANGE DUP BLKERR ! EXIT THEN
  DUP BLKN !
  0 BLKXFER            ( addr st )
  DUP BLKERR !         ( addr st )
  DUP 0= IF DROP 0 BLKDRT ! EXIT THEN   ( addr )   \ success: exactly one address
  SWAP DROP RAISE ;    ( st -- st )     \ failure: exactly one named code

: UPDATE ( -- )              \ the buffer is dirty; SAVE will send it
  -1 BLKDRT ! ;

: SAVE ( -- st )             \ send the buffer back as block BLKN; 0 = written
\ GUARDRAIL: P38 fix 3 — the old line was `BLKN @ 1 BLKXFER SWAP DROP DUP BLKERR ! 0= IF …THEN`.
\ `0=` consumed the status it was testing (TOS-only op) and the ZBRANCH popped the flag, so SAVE
\ returned nothing and the caller's `0 =` popped an empty stack (P37: underflow right after
\ w-save-blk0). DUP keeps the status for the return value; the flag the IF eats is the copy.
  BLKDRT @ IF BLKN @ 1 BLKXFER SWAP DROP DUP BLKERR !
           DUP 0= IF 0 BLKDRT ! THEN EXIT THEN
  0 ;

: BLK-ABORT ( -- )           \ drop an unanswered request instead of waiting for it forever
  0 2 BLKXFER SWAP DROP DROP 0 BLKERR ! ;
