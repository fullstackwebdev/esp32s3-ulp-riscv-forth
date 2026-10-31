\ test_block.fs - P33's host execution test. Load order:
\   host_blocks boot_min.fs blocks.fs test_block.fs
\ The fake server (uforth.c HOST block) holds block n byte k = k + 7n, answers blocks 0..3,
\ serves block 7 with a wrong checksum, and never answers any other number.

CREATE A 0 ,                 \ the address BLOCK returned
: K@ ( a k -- b ) + C@ ;
: T ( f -- ) IF ." PASS " ELSE ." FAIL " THEN ;
: NL 10 EMIT ;

." read-blk0  " 0 BLOCK A !
  A @ 0 K@ 0 =  A @ 3 K@ 3 =  AND  A @ 200 K@ 200 =  AND  A @ 511 K@ 255 =  AND T NL
." read-blk2  " 2 BLOCK A !
  A @ 0 K@ 14 =  A @ 1 K@ 15 =  AND  A @ 100 K@ 114 =  AND  A @ 511 K@ 13 =  AND T NL

\ write back: poke byte 9, UPDATE, SAVE. The server's copy of block 0 must then say 42.
." save-blk0  " 0 BLOCK A !
  42 A @ 9 + C!  UPDATE  SAVE 0 =  AND 0 BLKERR @ 0 = AND T NL
." reread     " 0 BLOCK A !  A @ 9 K@ 42 = T NL

\ no answer: block 15 is a black hole. BLKERR = -3, and the buffer must keep block 0's bytes.
." no-server  " 15 BLOCK -3 =  BLKERR @ -3 =  AND
  A @ 9 K@ 42 =  AND T NL
\ the unanswered request is still out there, so the next request is refused, not raced.
." busy       " 0 BLOCK -2 =  BLKERR @ -2 = AND T NL
." abort+read " BLK-ABORT 0 BLOCK A !  A @ 9 K@ 42 = T NL

\ bad checksum: block 7 answers with a checksum the client can see is wrong.
." crc        " 7 BLOCK -4 =  BLKERR @ -4 = AND T NL

\ the dirty flag is honest: a clean SAVE sends nothing.
." clean-save " SAVE 0 = T NL
