\ R5 block layer on the HOST build of the shipping engine (src/uforth.c with -DP33_BLOCK -DBLKPRIM).
\ The fake server (same file, #if defined(P33_BLOCK) in the HOST section) serves 4 blocks where block n
\ byte k = k + 7n, fails block 7 with a wrong checksum, and never answers any other number — so the
\ happy path, the checksum path and the no-answer path are all reachable from Forth alone.
\ GUARDRAIL: the happy path comes FIRST. A request that times out deliberately leaves blk_out set, so
\ every later call answers ERR_BUSY; the timeout case has its own file for exactly that reason.
0 BLOCK 0 BLOCK = .   \ GUARDRAIL: assert the window is STABLE, not that it equals a literal: the
                      \ address moved when MEMSZ moved (1200 -> 1936) and a hardcoded 1072 turned a good engine red.
65 0 BLOCK C! UPDATE SAVE .
0 BLOCK C@ .
1 BLOCK C@ .
70 0 BLOCK C! UPDATE
1 BLOCK .
SAVE .
0 BLOCK C@ .
-1 BLOCK .
7 BLOCK .
