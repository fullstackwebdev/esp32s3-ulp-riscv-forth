\ loop.fs — the resident event loop: rows 5, 8, 9, 13, 14 of the A/B. Runs with -k so the expected
\ ERR_NO_SERVER of row 13 does not end the file and its recovery can be asserted.
\ GUARDRAIL: the handlers are silent on purpose. With printing handlers the transcript interleaves handler
\ output with the assertions and becomes unreadable, which hid a real bug once already (a stray queue drain).
\ The rows are asserted through counters (brt, qovf, curblk), which is what the metrics ask for anyway.
0 BLOCK CONSTANT W
: BLKBLANK 0 BEGIN DUP 128 < WHILE 32 OVER W + C! 1 + REPEAT DROP ;
2 BLOCK DROP BLKBLANK UPDATE SAVE DROP      \ empty overlay: the rewind target
8 BLOCK DROP BLKBLANK
58 W 0 + C! 32 W 1 + C! 72 W 2 + C! 56 W 3 + C! 32 W 4 + C! 68 W 5 + C!
82 W 6 + C! 79 W 7 + C! 80 W 8 + C! 32 W 9 + C! 59 W 10 + C! 32 W 11 + C!
39 W 12 + C! 32 W 13 + C! 72 W 14 + C! 56 W 15 + C! 32 W 16 + C! 111 W 17 + C!
118 W 18 + C! 108 W 19 + C! 114 W 20 + C! 117 W 21 + C! 110 W 22 + C! 32 W 23 + C!
33 W 24 + C! 32 W 25 + C! 80 W 26 + C! 85 W 27 + C! 77 W 28 + C! 80 W 29 + C!
UPDATE SAVE DROP
9 BLOCK DROP BLKBLANK
58 W 0 + C! 32 W 1 + C! 72 W 2 + C! 57 W 3 + C! 32 W 4 + C! 68 W 5 + C!
82 W 6 + C! 79 W 7 + C! 80 W 8 + C! 32 W 9 + C! 59 W 10 + C! 32 W 11 + C!
39 W 12 + C! 32 W 13 + C! 72 W 14 + C! 57 W 15 + C! 32 W 16 + C! 111 W 17 + C!
118 W 18 + C! 108 W 19 + C! 114 W 20 + C! 117 W 21 + C! 110 W 22 + C! 32 W 23 + C!
33 W 24 + C! 32 W 25 + C! 80 W 26 + C! 85 W 27 + C! 77 W 28 + C! 80 W 29 + C!
UPDATE SAVE DROP
10 BLOCK DROP BLKBLANK
58 W 0 + C! 32 W 1 + C! 72 W 2 + C! 65 W 3 + C! 32 W 4 + C! 68 W 5 + C!
82 W 6 + C! 79 W 7 + C! 80 W 8 + C! 32 W 9 + C! 59 W 10 + C! 32 W 11 + C!
39 W 12 + C! 32 W 13 + C! 72 W 14 + C! 65 W 15 + C! 32 W 16 + C! 111 W 17 + C!
118 W 18 + C! 108 W 19 + C! 114 W 20 + C! 117 W 21 + C! 110 W 22 + C! 32 W 23 + C!
33 W 24 + C! 32 W 25 + C! 80 W 26 + C! 85 W 27 + C! 77 W 28 + C! 80 W 29 + C!
UPDATE SAVE DROP
SEAL

\ row 5: two events for the SAME phase cause ONE block round trip, not one per event.
\ GUARDRAIL: an event IS a phase block number (the loop does not map events to phases any more), so these
\ posts name blocks 8 and 9, not 0 and 1. Posting 0 asked to load block 0 - a real block - and the phase
\ never matched the seeded handler, which read as an empty queue.
8 POST 8 POST
brt @ .                  \ 0
8 PHASE
EV? .                    \ 0 - the loop drained both events
brt @ .                  \ 1

\ row 8: a full 4-slot ring rejects the fifth event and counts it (never silent)
9 POST 9 POST 9 POST 9 POST 9 POST
qovf @ .                 \ 1

\ row 9: 50 rotations across two phases leave the dictionary exactly sealed
RESET
: ROTATE 0 BEGIN DUP 50 < WHILE 8 PHASE 9 PHASE 1 + REPEAT DROP ;
ROTATE
2 OVL                    \ GUARDRAIL: rewind before comparing. After a rotation the LAST phase is still loaded, so
                         \ HERE is legitimately above the sealed value; comparing without this reads as a leak
                         \ (measured: 0 0 instead of -1 -1).
HERE bh @ = .            \ -1
LATEST bl @ = .          \ -1

\ row 13: a load of a block nobody answers fails by name; RESET recovers and the next load works
99 OVL                   \ must fail by name: ERR_NO_SERVER
0 2 BLKXFER DROP         \ GUARDRAIL: a timed-out request deliberately leaves blk_out latched, so every later block
                         \ call answers ERR_BUSY. BLKXFER with op 2 (BLK_ABORT) is the documented escape hatch;
                         \ without it the machine is wedged and row 13's recovery cannot even be tested.
RESET
curblk @ .               \ -1
qovf @ .                 \ 0 - RESET clears the counter
8 PHASE
curblk @ .               \ 8 - the machine is usable again
