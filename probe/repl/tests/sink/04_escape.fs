: ESC ( -- ) 27 EMIT ;
: CSI ( -- ) 91 EMIT ;
: M ( -- ) 109 EMIT ;
: SENT ( -- ) 0 EMIT ;
: COL ( n -- ) 7 AND ESC CSI 51 EMIT 48 + EMIT M ;
: FRAME ( -- ) ESC CSI 50 EMIT 74 EMIT 1 COL ." ok" SENT ;
: RUNSINK ( -- ) FRAME ;
