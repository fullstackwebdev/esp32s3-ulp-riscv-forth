CREATE NXT 0 ,
: CHAIN ( desc -- ) NXT ! ;
: RW ( -- ) bh @ VH ! bl @ VL ! ;
: NOOP ( -- ) ;
: UNLATCH ( -- ) 0 2 BLKXFER DROP DROP ;
: PICKX ( desc -- xt ) RW 3 BLKXFER DUP IF DROP DROP UNLATCH ['] NOOP ELSE DROP @ THEN ;
: SWITCH ( desc -- ) NXT ! BEGIN NXT @ WHILE NXT @ PICKX 0 NXT ! EXECUTE REPEAT ;
: GO ( desc -- ) SWITCH ;
