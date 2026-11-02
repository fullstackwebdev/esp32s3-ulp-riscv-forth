\ lora1.fs - SX1262 transmit driver in Forth, via the HW gate.
\ Pads are muxed by the main core at boot; nothing here touches
\ RTC IO mux. Lines under 63 B; no loop may span lines.

8  CONSTANT NSS
9  CONSTANT SCK
10 CONSTANT MOSI
11 CONSTANT MISO
12 CONSTANT NRST
13 CONSTANT BUSY
14 CONSTANT DIO1

\ 0x60008404 OUT_W1TS, 0x60008408 OUT_W1TC, 0x60008424 IN
\ Data sits at bit 10 of each register, hence the 10 +.
1610646532 CONSTANT SET
1610646536 CONSTANT CLR
1610646564 CONSTANT IN

: !P ( level pin -- )
  10 + 1 SWAP LSHIFT SWAP IF SET ELSE CLR THEN ! ;
: @P ( pin -- level ) 10 + 1 SWAP LSHIFT IN @ AND 0= 0= ;

: S ( b -- b*2 )
  DUP 128 AND IF 1 MOSI !P ELSE 0 MOSI !P THEN
  1 SCK !P 0 SCK !P 2 * ;
: >B ( b -- ) S S S S S S S S DROP ;

\ one clock with MOSI low and no read, for bits we throw away
: K 0 MOSI !P 1 SCK !P 0 SCK !P ;
\ one clock that returns MISO
: <C ( -- bit ) 0 MOSI !P 1 SCK !P MISO @P 0 SCK !P ;

: [ 0 NSS !P ;
: ] 1 NSS !P ;
: C1 ( op arg -- ) [ SWAP >B >B ] ;

\ BUSY settle, no loop: run_line zeroes the stack each line,
\ BEGIN keeps markers there. Settle 1 ms, then check.
: WB ( -- ok ) 1 MS BUSY @P 0= ;

: RST ( -- ok ) 0 NRST !P 2 MS 1 NRST !P 5 MS WB ;

: INIT ( -- ok )
  1 NSS !P 1 NRST !P 0 SCK !P
  RST 0= IF 0 EXIT THEN
  [ 128 >B 0 >B ] [ 150 >B 1 >B ]
  [ 151 >B 2 >B 0 >B 1 >B 64 >B ]
  [ 137 >B 127 >B ] [ 157 >B 1 >B ] [ 138 >B 1 >B ]
  [ 134 >B 54 >B 65 >B 153 >B 153 >B ]
  [ 152 >B 215 >B 219 >B ]
  [ 149 >B 2 >B 2 >B 0 >B 1 >B ]
  [ 142 >B 14 >B 4 >B ]
  [ 143 >B 0 >B 0 >B ]
  [ 139 >B 9 >B 4 >B 1 >B 0 >B ]
  [ 140 >B 0 >B 8 >B 0 >B 4 >B 1 >B 0 >B ]
  [ 8 >B 2 >B 1 >B 2 >B 1 >B 0 >B 0 >B 0 >B 0 >B ]
  1 ;

\ 4-byte payload; IRQ cleared BEFORE SetTx (DIO1 is a LEVEL),
\ past the air time and read TxDone (bit 0 arrives last).
: SEND ( -- ok )
  [ 14 >B 0 >B 165 >B 49 >B 50 >B 51 >B ]
  [ 2 >B 255 >B 255 >B ]
  [ 131 >B 15 >B 0 >B 0 >B ]
  150 MS
  [ 18 >B 0 >B
    K K K K K K K K K K K K K K K <C ]
  1 AND ;

: SLEEP 132 4 C1 ;
