( reader logic - the page/line arithmetic and the bookmark round trip through READ_ST )
( load AFTER examples/apps/reader/read1.fs: the words under test are the phase's own, not a copy )
( GUARDRAIL - registry cells are 4 B apart, so READ_ST 1 + lands INSIDE the page cell - use 4 + and 8 + )
: NL 10 EMIT ;
: CK ( got want -- ) OVER OVER = IF ." ok" DROP DROP ELSE ." FAIL " SWAP . ." <> " . THEN ;
( the three cells are the three fields: writing one must not disturb the others )
." cells 5,6,7=" 5 READ_ST ! 6 READ_ST 4 + ! 7 READ_ST 8 + ! READ_ST @ 5 CK READ_ST 4 + @ 6 CK READ_ST 8 + @ 7 CK NL
( RT is the top line that READ_ST page and column address: page*8 + column )
." rt(0,0)=" 0 READ_ST ! 0 READ_ST 4 + ! RT 0 CK NL
." rt(0,7)=" 7 READ_ST 4 + ! RT 7 CK NL
." rt(1,0)=" 1 READ_ST ! 0 READ_ST 4 + ! RT 8 CK NL
." rt(2,5)=" 2 READ_ST ! 5 READ_ST 4 + ! RT 21 CK NL
." rt(7,0)=" 7 READ_ST ! 0 READ_ST 4 + ! RT 56 CK NL
( RSET is the inverse, and the /MOD order is the trap: the quotient is the page, the remainder the column )
." rset page=" 21 RSET READ_ST @ 2 CK ." rset col=" READ_ST 4 + @ 5 CK NL
( every reachable top line survives line -> page/column -> line, 0..56 inclusive )
( GUARDRAIL - a BEGIN..WHILE..REPEAT written at TOP LEVEL leaves BEGIN's HERE and WHILE's branch )
( GUARDRAIL - address on the data stack, so the counter prints as HERE, 1896 - loops go in a word )
: RT0 ( -- ) 0 BEGIN DUP 57 < WHILE DUP RSET RT OVER = IF ." ok " ELSE ." FAIL " THEN 1+ REPEAT DROP ;
." round trip 0..56 " RT0 NL
( the window may not run off either end of the text: 8 lines from the last top line is the end )
." clamp -1=" -1 RCLAMP 0 CK ." clamp 0=" 0 RCLAMP 0 CK NL
." clamp 56=" 56 RCLAMP 56 CK ." clamp 57=" 57 RCLAMP 56 CK ." clamp 63=" 63 RCLAMP 56 CK NL
( a key moves the top line by one, across a page boundary and back )
." next 0->1=" 0 RSET RNEXT RT 1 CK ." next 7->8=" 7 RSET RNEXT RT 8 CK NL
." prev 8->7=" 8 RSET RPREV RT 7 CK ." prev 21->20=" 21 RSET RPREV RT 20 CK NL
( clamped at the ends )
." next at end=" 56 RSET RNEXT RT 56 CK ." prev at start=" 0 RSET RPREV RT 0 CK NL
( RBLK is the block a visible line comes from: the app's base 80 plus the top line plus the row )
." blk page0 row0=" 0 RSET 0 RBLK 80 CK ." blk page0 row7=" 7 RBLK 87 CK NL
." blk page1 row0=" 8 RSET 0 RBLK 88 CK ." blk page1 row3=" 3 RBLK 91 CK NL
( the bookmark is ONE cell: m writes the top line, g reads it back and rebuilds page and column )
." mark at 21=" 21 RSET RMARK READ_ST 8 + @ 21 CK ." then 40=" 40 RSET RT 40 CK NL
." g returns to=" RGO RT 21 CK ." mark kept=" READ_ST 8 + @ 21 CK NL
( a page turn does not disturb the mark, and g restores the exact line, column included )
." mark 13, paged=" 13 RSET RMARK 56 RSET RT 56 CK ." g from 56=" RGO RT 13 CK NL
." g cell=" READ_ST 4 + @ 5 CK ." g page=" READ_ST @ 1 CK NL
( the title's page number is the page cell plus one, and page 8 is the last of the eight )
." label page1=" 0 RSET READ_ST @ 1+ 1 CK ." label page8=" 56 RSET READ_ST @ 1+ 8 CK NL
( RPOS shows the column within the page and the mark, both 1-based )
." line in page=" 21 RSET READ_ST 4 + @ 1+ 6 CK ." mark shown=" READ_ST 8 + @ 1+ 14 CK NL
