\ overlay.fs — resident/overlay split, tested against the fake block server (blocks 0..3 answer).
\ Runs only against artifacts/host_blk (blocks + OVL_LOAD) with src/p39b_overlay.fs loaded.
\
\ Block 0 holds an overlay that defines HI; block 2 is deliberately EMPTY, so `2 OVL` rewinds the
\ dictionary and compiles nothing — which is the only way to observe the free space returning exactly to
\ the sealed value. This is the friend's test order:
\   (a) SEAL, then load a word through OVL and run it
\   (b) a second OVL returns the free space to the sealed value
\   (c) a sealed word still works after the overlay has been dropped
\   (d) the overlay's entry point is reachable through the hook cell
\
\ GUARDRAIL: blank a block before writing into it. A block is 128 characters and LOAD interprets ALL of
\ them; the first version of this test wrote 12 bytes and left the fake server's filler (byte k = k + 7n)
\ as source. Some filler is valid Forth, so the failure is not always loud - it can compile junk into the
\ overlay and only show up as a wrong number later.
\ GUARDRAIL: UPDATE before SAVE. SAVE is a no-op on a clean buffer and returns 0 either way, so a test that
\ skips UPDATE looks like a successful save and then loads the block's ORIGINAL contents.
\ GUARDRAIL: a block must be SAVEd before fetching a different one; BLOCK refuses a different block while
\ the window is dirty (BK_DIRTY) rather than discarding the edits.

0 BLOCK CONSTANT W          \ the window address, from the engine - never a literal
\ GUARDRAIL: W is defined before the word that uses it; a colon body resolves names at compile time, so
\ a definition placed above its dependency compiles a reference that fails at run time, naming the word
\ rather than the ordering mistake.
: BLKBLANK ( -- ) 0 BEGIN DUP 128 < WHILE 32 OVER W + C! 1 + REPEAT DROP ;
BLKBLANK
\ ": HI 42 . ; "
58 W  0 + C!  32 W  1 + C!  72 W  2 + C!  73 W  3 + C!  32 W  4 + C!
52 W  5 + C!  50 W  6 + C!  32 W  7 + C!  46 W  8 + C!  32 W  9 + C!
59 W 10 + C!  32 W 11 + C!
UPDATE
SAVE .                      \ must print 0 (BK_OK)

2 BLOCK DROP                \ the empty overlay
BLKBLANK
UPDATE
SAVE .                      \ must print 0

\ (a) resident, then seal
: RES 7 . ;                 \ a sealed word, re-checked after the overlay is dropped
LATEST HERE - CONSTANT F0   \ free space before any overlay
SEAL
32 EMIT LATEST . 32 EMIT HERE . 32 EMIT F0 . 32 EMIT
0 OVL
32 EMIT LATEST . 32 EMIT HERE . 32 EMIT
2 OVL
32 EMIT LATEST . 32 EMIT HERE . 32 EMIT F0 . 32 EMIT
