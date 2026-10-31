CREATE A 0 ,
: K@ ( a k -- b ) + C@ ;
: T  ( f -- ) IF ." PASS" 10 EMIT EXIT THEN ." FAIL" 10 EMIT ;
: R0 ( -- )  0 BLOCK A ! A @ 0 K@ 0 = A @ 3 K@ 3 = AND A @ 200 K@ 200 = AND T ;
." one " 10 EMIT
." two " R0
." three " 10 EMIT
." four " 10 EMIT
