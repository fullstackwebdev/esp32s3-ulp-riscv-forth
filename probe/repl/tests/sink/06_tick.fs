CREATE N 0 ,
: NOOP ( -- ) ;
: BUMP ( -- ) N @ 1+ N ! ;
: TWO ( -- ) ['] BUMP EXECUTE ['] BUMP EXECUTE ;
: RUNSINK ( -- ) TWO N @ . ;
