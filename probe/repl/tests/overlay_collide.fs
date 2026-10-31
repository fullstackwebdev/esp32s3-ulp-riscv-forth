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
