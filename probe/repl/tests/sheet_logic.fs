\ sheet_logic.fs — the arithmetic examples/apps/sheet/sheet1.fs runs, as words.
\ GUARDRAIL: the phase's own words cannot be loaded here — a phase source is BLOCK-uploaded and this machine has
\ no INCLUDE — so this file MIRRORS the four formulas: WRAP/MV (cursor wrap, 0-based cells), CIO/CAD (cell
\ addressing) and R3/RSUM (row sum). Keep the names and the formulas in step with the phase, or this certifies a
\ copy that nobody ships.
\ GUARDRAIL: every case prints `ok ` or `BAD `, so a formula that drifts shows up in the golden as BAD rather than
\ as a shifted number (R12: a green suite certifies only what it examines). The cases are the four cursor keys at
\ a wrap edge and in the middle (8 assertions), five cell addresses plus the byte offsets, and three row sums.
: SP ( -- ) 32 EMIT ;
: CK ( got want -- ) = IF ." ok" ELSE ." BAD" THEN SP ;
\ cursor wrap: cells are 0-BASED, so -1 wraps to 5 — add 6, then /MOD by 6. No DO/LOOP, no MOD on this machine.
: WRAP ( n d -- n' ) SWAP + 6 + 6 /MOD DROP ;
\ the phase's own MV, unchanged: it reads the cell, wraps, writes it back
: MV ( d a -- ) DUP @ ROT + 6 + 6 /MOD DROP SWAP ! ;
\ h on a column: 0-1 wraps to 5, 3-1 is 2
0 -1 WRAP 5 CK
3 -1 WRAP 2 CK
\ l on a column: 5+1 wraps to 0, 1+1 is 2
5 1 WRAP 0 CK
1 1 WRAP 2 CK
\ k/j through MV on a real cell: up from row 0 wraps to 5, up from 4 is 3, down from 5 wraps to 0, down from 2 is 3
CREATE K0 0 ,
CREATE K4 4 ,
CREATE J5 5 ,
CREATE J2 2 ,
-1 K0 MV K0 @ 5 CK
-1 K4 MV K4 @ 3 CK
1 J5 MV J5 @ 0 CK
1 J2 MV J2 @ 3 CK
\ cell addressing: index = row*6 + col, byte offset = 2 * index (one 16-bit value per cell)
: CIO ( row col -- i ) SWAP 6 * + ;
: CAD ( row col -- b ) CIO 2 * ;
0 0 CIO 0 CK
0 5 CIO 5 CK
5 0 CIO 30 CK
5 5 CIO 35 CK
2 3 CIO 15 CK
5 5 CAD 70 CK
\ row sum: three halfwords twice, the same shape R3/RSUM use (a row is 6 cells = 12 bytes)
: CLP ( n -- n ) DUP 100 U< IF ELSE DROP 99 THEN ;
: R3 ( s -- n s' ) DUP W@ CLP OVER 2 + W@ CLP + OVER 4 + W@ CLP + SWAP 6 + ;
: RSUM ( s -- n ) R3 R3 DROP + ;
CREATE V 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 , 0 ,
: V! ( n i -- ) 2 * V + W! ;
1 0 V! 2 1 V! 3 2 V! 4 3 V! 5 4 V! 6 5 V!
10 6 V! 20 7 V! 30 8 V! 40 9 V! 50 10 V! 60 11 V!
7 30 V! 8 31 V! 9 32 V!
V 0 + RSUM 21 CK
V 12 + RSUM 210 CK
V 60 + RSUM 24 CK
\ a stored value over the displayable range is CLAMPED on the way out, so the sum agrees with the cells on screen
150 6 V!
V 12 + RSUM 299 CK
