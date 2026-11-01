( reader logic - page/line arithmetic, clamp, block address, bookmark round trip )
( loaded AFTER read1.fs + the app-store resident, on host_app at device geometry )
( GUARDRAIL - no helper words here on purpose: the phase leaves 58 B of window, so a )
( GUARDRAIL - CK/NL pair would not fit the dictionary - print values, the golden asserts )
( GUARDRAIL - cells are 4 B apart - READ_ST 1 + is INSIDE the page cell, use 4 + and 8 + )
( the three cells are page, column, mark: writing one must not disturb the others )
." cells=" 1 READ_ST ! 5 READ_ST 4 + ! 3 READ_ST 8 + !
READ_ST @ . SP READ_ST 4 + @ . SP READ_ST 8 + @ . 10 EMIT
( RT is the top line a page/column pair addresses: page*8 + column )
." rt(0,0)=" 0 READ_ST ! 0 READ_ST 4 + ! RT . SP ." rt(0,7)=" 7 READ_ST 4 + ! RT . 10 EMIT
." rt(1,0)=" 1 READ_ST ! 0 READ_ST 4 + ! RT . SP ." rt(1,5)=" 5 READ_ST 4 + ! RT . 10 EMIT
( RSET is the inverse: /MOD leaves rem under quot, so quot is the page, rem the column )
." rset 13 page=" 13 RSET READ_ST @ . SP ." col=" READ_ST 4 + @ . 10 EMIT
( every reachable top line survives line -> page/column -> line: 0..8 )
." trip=" 0 RSET RT . SP 1 RSET RT . SP 2 RSET RT . SP 3 RSET RT . SP 4 RSET RT . 10 EMIT
." trip=" 5 RSET RT . SP 6 RSET RT . SP 7 RSET RT . SP 8 RSET RT . 10 EMIT
( the window may not run off either end: the last top line is 2 pages x 8 - 8 )
." clamp=" -1 RCLAMP . SP 0 RCLAMP . SP 8 RCLAMP . SP 9 RCLAMP . SP 63 RCLAMP . 10 EMIT
( a key moves the top line by one, across the page boundary and back )
." next 0=" 0 RSET RNEXT RT . SP ." next 7=" 7 RSET RNEXT RT . 10 EMIT
." prev 8=" 8 RSET RPREV RT . SP ." prev 5=" 5 RSET RPREV RT . 10 EMIT
( clamped at the ends: neither end may step outside the document )
." next end=" 8 RSET RNEXT RT . SP ." prev start=" 0 RSET RPREV RT . 10 EMIT
( RBLK is the block a visible line comes from: base 64 plus top line plus row )
." blk p1=" 0 RSET 0 RBLK . SP 7 RBLK . 10 EMIT
." blk p2=" 8 RSET 0 RBLK . SP 3 RBLK . 10 EMIT
." last blk=" 8 RSET 7 RBLK . 10 EMIT
( the bookmark is ONE cell: m writes the top line, g rebuilds page and column )
." mark 3=" 3 RSET RMARK READ_ST 8 + @ . SP ." moved 8=" 8 RSET RT . 10 EMIT
." g back=" RGO RT . SP ." page=" READ_ST @ . SP ." col=" READ_ST 4 + @ . 10 EMIT
." mark kept=" READ_ST 8 + @ . 10 EMIT
( the title's page number is the page cell plus one, and page 2 is the last of two )
." label=" 0 RSET READ_ST @ 1+ . SP 8 RSET READ_ST @ 1+ . 10 EMIT
( RPOS shows the column within the page and the mark, both 1-based )
." line=" 5 RSET READ_ST 4 + @ 1+ . SP ." mark shown=" READ_ST 8 + @ 1+ . 10 EMIT
