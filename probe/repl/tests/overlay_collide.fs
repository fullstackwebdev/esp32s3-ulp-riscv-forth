\ overlay_collide.fs — test 4: an overlay word that collides with a RESIDENT name is refused loudly.
\ Runs only against artifacts/host_blk with src/p39b_overlay.fs, and needs -k (keep going after the error)
\ because the refusal IS the assertion and the point of the test is what survives it.
\
\ GUARDRAIL: `RES` is resident, so a block redefining RES hashes to the same 12-bit value. Before mkentry grew
\ the V_SEAL check this test would have printed `1` for RES instead of `7` - a silently shadowed resident word,
\ which is the failure this dictionary cannot report at run time.
\
\ GUARDRAIL: the block must be blanked and SAVEd like any other; block 1 is not one of the fake server's
\ pre-filled blocks, so without the write it would answer with filler bytes and the overlay would compile junk.

0 BLOCK CONSTANT W
: BLKBLANK 0 BEGIN DUP 128 < WHILE 32 OVER W + C! 1 + REPEAT DROP ;
: RES 7 . ;
SEAL

1 BLOCK DROP               \ the bad overlay: ": RES 1 . ; "
BLKBLANK
58 W 0 + C! 32 W 1 + C! 82 W 2 + C! 69 W 3 + C! 83 W 4 + C!
32 W 5 + C! 49 W 6 + C! 32 W 7 + C! 46 W 8 + C! 32 W 9 + C!
59 W 10 + C! 32 W 11 + C!
UPDATE
SAVE DROP

1 OVL                      \ must be refused with ERR_DICT: nothing is written
RES                        \ must still print 7 - the resident definition, untouched
HERE bh @ = .              \ must print -1: the refused definition moved no pointer
LATEST bl @ = .            \ must print -1
NOPE                       \ control: a name that was never defined still errors (prints NOPE?)

\ (h) a collision INSIDE one overlay must be refused too. The scan used to start at V_SEAL, i.e. at the
\ resident headers only, so two names colliding within the same phase were invisible - and at ~2.4 % per name
\ that case is likely enough to hide among the loud ones.
3 BLOCK DROP
BLKBLANK
58 W 0 + C! 32 W 1 + C! 68 W 2 + C! 85 W 3 + C! 80 W 4 + C! 69 W 5 + C!
32 W 6 + C! 49 W 7 + C! 32 W 8 + C! 46 W 9 + C! 32 W 10 + C! 59 W 11 + C!
32 W 12 + C! 58 W 13 + C! 32 W 14 + C! 68 W 15 + C! 85 W 16 + C! 80 W 17 + C!
69 W 18 + C! 32 W 19 + C! 50 W 20 + C! 32 W 21 + C! 46 W 22 + C! 32 W 23 + C!
59 W 24 + C! 32 W 25 + C!
UPDATE SAVE DROP
\ GUARDRAIL: blank block 2 before rewinding through it. The rewind target must hold NOTHING; with the loader fixed
\ to deliver a whole block, the fake server's filler (byte k = k + 14 here) is executed in full and prints garbage -
\ the old loader dropped most of it, which is why this test passed while the loader was wrong.
2 BLOCK DROP BLKBLANK UPDATE SAVE DROP
2 OVL                        \ rewind to the sealed state
3 OVL                        \ the second DUPE must be refused: prints DUPE?
DUPE                         \ must print 1 - the FIRST definition survived
