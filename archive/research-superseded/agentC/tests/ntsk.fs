\ NTSK bound: the task table holds TWO records. A third SPAWN must refuse BY NAME and set errf, which
\ aborts the rest of this file — that is the expected output, not a failure (a deliberate error cannot
\ live in suite.fs, where an abort would swallow the remaining assertions).
: TA 1 . PAUSE 2 . ;
: TB 3 . PAUSE 4 . ;
: TC 5 . PAUSE 6 . ;
SPAWN TA SPAWN TB SPAWN TC
THERE-IS-NO-SUCH-WORD
