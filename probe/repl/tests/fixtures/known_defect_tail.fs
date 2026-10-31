\ known_defect_tail.fs — a definition whose closing ';' lies PAST the chip's 96-byte tib pass.
\
\ GUARDRAIL: this probe states the CORRECT behaviour (the word resolves and runs), so a fix reports FIXED and
\ the probe is promoted to a real test instead of a golden file being written around the gap.
\
\ The defect: a block longer than TIBSZ is delivered in two passes; blk_refill cuts the first pass back to a
\ space and the tail is delivered on the second pass, which can arrive AFTER the next line has begun. Measured
\ on the host trace as the next line's tokens being read at STATE=1 (compiled into the open definition) with the
\ stray ';' arriving afterwards. The block below is 97 bytes, so its ';' is beyond offset 95.

0 BLOCK CONSTANT W
: BLKBLANK ( -- ) 0 BEGIN DUP 128 < WHILE 32 OVER W + C! 1 + REPEAT DROP ;
BLKBLANK
58 W  0 + C!
32 W  1 + C!
84 W  2 + C!
65 W  3 + C!
73 W  4 + C!
76 W  5 + C!
84 W  6 + C!
69 W  7 + C!
83 W  8 + C!
84 W  9 + C!
32 W 10 + C!
52 W 11 + C!
50 W 12 + C!
32 W 13 + C!
46 W 14 + C!
32 W 15 + C!
49 W 16 + C!
32 W 17 + C!
49 W 18 + C!
32 W 19 + C!
49 W 20 + C!
32 W 21 + C!
49 W 22 + C!
32 W 23 + C!
49 W 24 + C!
32 W 25 + C!
49 W 26 + C!
32 W 27 + C!
49 W 28 + C!
32 W 29 + C!
49 W 30 + C!
32 W 31 + C!
49 W 32 + C!
32 W 33 + C!
49 W 34 + C!
32 W 35 + C!
49 W 36 + C!
32 W 37 + C!
49 W 38 + C!
32 W 39 + C!
49 W 40 + C!
32 W 41 + C!
49 W 42 + C!
32 W 43 + C!
49 W 44 + C!
32 W 45 + C!
49 W 46 + C!
32 W 47 + C!
49 W 48 + C!
32 W 49 + C!
49 W 50 + C!
32 W 51 + C!
49 W 52 + C!
32 W 53 + C!
49 W 54 + C!
32 W 55 + C!
49 W 56 + C!
32 W 57 + C!
49 W 58 + C!
32 W 59 + C!
49 W 60 + C!
32 W 61 + C!
49 W 62 + C!
32 W 63 + C!
49 W 64 + C!
32 W 65 + C!
49 W 66 + C!
32 W 67 + C!
49 W 68 + C!
32 W 69 + C!
49 W 70 + C!
32 W 71 + C!
49 W 72 + C!
32 W 73 + C!
49 W 74 + C!
32 W 75 + C!
49 W 76 + C!
32 W 77 + C!
49 W 78 + C!
32 W 79 + C!
49 W 80 + C!
32 W 81 + C!
49 W 82 + C!
32 W 83 + C!
49 W 84 + C!
32 W 85 + C!
49 W 86 + C!
32 W 87 + C!
49 W 88 + C!
32 W 89 + C!
49 W 90 + C!
32 W 91 + C!
49 W 92 + C!
32 W 93 + C!
49 W 94 + C!
32 W 95 + C!
59 W 96 + C!
UPDATE
SAVE DROP

0 OVL
TAILTEST            \ correct: prints 42 (defect: answers TAILTEST?)
