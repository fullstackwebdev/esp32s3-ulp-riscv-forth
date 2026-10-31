\ test_proto.fs - P33 host execution, one check per line.
\   host_blocks src/boot16.fs src/test_proto.fs
\ The four protocol results are driven through the engine's own BLKXFER primitive; section 2.4 of
\ RESULT.md records why the Forth wrapper (BLOCK/UPDATE/SAVE) is not driven by this file.
CREATE A 0 ,
: K@ ( a k -- b ) + C@ ;
: T ( f -- ) IF ." PASS" 10 EMIT EXIT THEN ." FAIL" 10 EMIT ;
." read-blk0    " 0 0 BLKXFER SWAP A ! T
." blk0[3]=3    " A @ 3 K@ 3 = T
." blk0[200]    " A @ 200 K@ 200 = T
." read-blk2    " 2 0 BLKXFER SWAP A ! T
." blk2[100]    " A @ 100 K@ 114 = T
." save-blk0    " 0 0 BLKXFER SWAP A ! DROP 42 A @ 9 + C! 0 1 BLKXFER SWAP DROP T
." reread-blk0  " 0 0 BLKXFER SWAP A ! DROP A @ 9 K@ 42 = T
." no-server    " 15 0 BLKXFER SWAP DROP -3 = T
." no-zero-fill " A @ 9 K@ 42 = T
." busy         " 0 0 BLKXFER SWAP DROP -2 = T
." abort+read   " 0 2 BLKXFER SWAP DROP DROP 0 0 BLKXFER SWAP A ! T
." reread-ok    " A @ 9 K@ 42 = T
." crc          " 7 0 BLKXFER SWAP DROP -4 = T
