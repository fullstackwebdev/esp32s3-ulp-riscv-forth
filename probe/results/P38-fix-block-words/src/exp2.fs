\ exp2.fs - P37 experiment 2: the real wrapper words, with the mailbox serviced *inside* the word.
\   timeout 15 host_blocks boot37.fs blocks.fs exp2.fs
\ The host fake server answers at the doorbell (pl_hw op 6), i.e. inside blk_xfer, before the poll
\ loop runs at all: "the main core answers while the ULP is still inside the word". No harness hook
\ can do better, and nothing about this model changed between P33 and here.
CREATE A 0 ,
: K@ ( a k -- b ) + C@ ;
: T  ( f -- ) IF ." PASS" 10 EMIT EXIT THEN ." FAIL" 10 EMIT ;
: R0 ( -- )  0 BLOCK A ! A @ 0 K@ 0 = A @ 3 K@ 3 = AND A @ 200 K@ 200 = AND T ;
: R2 ( -- )  2 BLOCK A ! A @ 100 K@ 114 = T ;
: SV ( -- )  0 BLOCK A ! 42 A @ 9 + C! UPDATE SAVE 0 = BLKERR @ 0 = AND T ;
: RR ( -- )  0 BLOCK A ! A @ 9 K@ 42 = T ;
: NS ( -- )  15 BLOCK -3 = BLKERR @ -3 = AND T ;
: BS ( -- )  0 BLOCK -2 = BLKERR @ -2 = AND T ;
: AB ( -- )  BLK-ABORT 0 BLOCK A ! A @ 9 K@ 42 = T ;
: CR ( -- )  7 BLOCK -4 = BLKERR @ -4 = AND T ;
." w-read-blk0  " R0
." w-read-blk2  " R2
." w-save-blk0  " SV
." w-reread-blk0 " RR
." w-no-server  " NS
." w-busy        " BS
." w-abort+read " AB
." w-crc         " CR
