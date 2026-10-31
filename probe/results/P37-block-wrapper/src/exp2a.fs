CREATE A 0 ,
: K@ ( a k -- b ) + C@ ;
: P  ( f -- ) IF 65 EMIT ELSE 66 EMIT THEN ;   \ A = true, B = false
: R0 ( -- ) 0 BLOCK A ! ;
: D1 ( -- ) BLKERR @ 0= P A @ 1792 = P BLKDRT @ 0= P 10 EMIT ;
: D2 ( -- ) 1792 0 K@ 0 = P 1792 3 K@ 3 = P 1792 200 K@ 200 = P 10 EMIT ;
." d1 " R0 D1
." d2 " D2
