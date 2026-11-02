\ lora1.fs - SX1262 transmit driver in Forth, on the ULP-
\ RISC-V.
\
\ The pins are set up HERE, by the coprocessor. F-176
\ measured that a
\ store to RTC_GPIO_OUT_W1TS from the ULP does nothing until
\ the ULP
\ itself has set the SENS clock gate, pad MUX_SEL, FUN_SEL =
\ 0 and
\ RTC_GPIO_ENABLE_W1TS. That is why no bisect of program
\ content could
\ flip the answer: the missing ingredient was configuration,
\ and it has
\ to be written by the master that drives the pad.
\
\ NAMES ARE NOT COSMETICS. A header is 24 bits: imm(1) |
\ xt(11) |
\ hash(12), and no names are stored, so a 12-bit djb2 hash
\ IS a word's
\ identity. `SET`, `CLR`, `IN`, `SCK`, `MISO`, `BUSY` hash
\ onto resident
\ words and the chip refuses them with `SCK?`, which for
\ months looked
\ like "the coprocessor cannot drive the pads".
\ tools/hashcheck.py is a
\ lint rule, so a colliding name never reaches the board.
\
\ Lines stay under 63 bytes (the device input ring).
\
\ BUDGET: this driver needs MEMSZ >= 2550 of the pool. At 2540 the last two words (INIT, SEND) fall off the
\ end of the dictionary - the code area and the header area meet in the middle, so the name that disappears
\ is whichever is furthest down, and NOTHING reports it. `#k` and a `WORDS`-style probe will not show it;
\ only loading the file and asking for the last word does.

1610646532 CONSTANT PADSETW
1610646536 CONSTANT PADCLRW
1610646564 CONSTANT PADINRD
1610646544 CONSTANT PADENAB
1610646660 CONSTANT PADIO000
1610647812 CONSTANT PADCLKG

8  CONSTANT NSSPAD
9  CONSTANT SCKPAD
10 CONSTANT MOSIPAD
11 CONSTANT MISOPAD
12 CONSTANT NRSTPAD
13 CONSTANT BUSYPAD
14 CONSTANT DIO1PAD

: PADADR ( pad -- addr ) 4 * PADIO000 + ;
: PADBITSET ( pad bit -- ) SWAP PADADR DUP @ ROT OR SWAP ! ;
: PADBITCLR ( pad bit -- )
  SWAP PADADR DUP @ ROT INVERT AND SWAP ! ;

: PIN! ( level pin -- )
  10 + 1 SWAP LSHIFT SWAP IF PADSETW ELSE PADCLRW THEN ! ;
: PIN@ ( pin -- level ) 10 + 1 SWAP LSHIFT PADINRD AND 0= 0= ;

: CLOCKGATEON ( -- ) PADCLKG @ 1 31 LSHIFT OR PADCLKG ! ;
: FUNSEL-MASK ( -- m ) 1 17 LSHIFT 1 18 LSHIFT OR ;
: PADRTCMODE ( pad -- pad )
  DUP 1 19 LSHIFT PADBITSET DUP FUNSEL-MASK PADBITCLR ;
: ENSHIFT ( pad -- w ) 10 + 1 SWAP LSHIFT ;
: PADTOOUT ( pad -- ) PADRTCMODE ENSHIFT PADENAB ! ;
: PADTOIN ( pad -- ) PADRTCMODE 1 13 LSHIFT PADBITSET ;

: PINSRTC ( -- )
  CLOCKGATEON
  9 PADTOOUT 10 PADTOOUT 8 PADTOOUT 12 PADTOOUT
  11 PADTOIN 13 PADTOIN 14 PADTOIN
  1 NSSPAD PIN! 1 NRSTPAD PIN! 0 SCKPAD PIN! ;

: BITOUT ( b -- b*2 )
  DUP 128 AND IF 1 MOSIPAD PIN! ELSE 0 MOSIPAD PIN! THEN
  1 SCKPAD PIN! 0 SCKPAD PIN! 2 * ;
: >BYTE ( b -- )
  BITOUT BITOUT BITOUT BITOUT
  BITOUT BITOUT BITOUT BITOUT DROP ;
: NSSLO 0 NSSPAD PIN! ;
: NSSHI 1 NSSPAD PIN! ;
: BITREAD ( b -- b' )
  2 * 1 SCKPAD PIN! MISOPAD PIN@ 0 SCKPAD PIN! IF 1 + THEN ;
: CLOCKLOW ( -- ) 0 MOSIPAD PIN! 1 SCKPAD PIN! 0 SCKPAD PIN! ;

: BUSYOK ( -- ok ) 1 MS BUSYPAD PIN@ 0= ;

: RADIORESET ( -- ok )
  0 NRSTPAD PIN! 2 MS 1 NRSTPAD PIN! 5 MS BUSYOK ;
: INIT ( -- ok )
  PINSRTC
  1 NSSPAD PIN! 1 NRSTPAD PIN! 0 SCKPAD PIN!
  RADIORESET 0= IF 0 EXIT THEN
  NSSLO 128 >BYTE 0 >BYTE NSSHI
  NSSLO 150 >BYTE 1 >BYTE NSSHI
  NSSLO 151 >BYTE 2 >BYTE 0 >BYTE 1 >BYTE 64 >BYTE NSSHI
  NSSLO 137 >BYTE 127 >BYTE NSSHI
  NSSLO 157 >BYTE 1 >BYTE NSSHI
  NSSLO 138 >BYTE 1 >BYTE NSSHI
  NSSLO 134 >BYTE 54 >BYTE 65 >BYTE 153 >BYTE 153 >BYTE NSSHI
  NSSLO 152 >BYTE 215 >BYTE 219 >BYTE NSSHI
  NSSLO 149 >BYTE 2 >BYTE 2 >BYTE 0 >BYTE 1 >BYTE NSSHI
  NSSLO 142 >BYTE 14 >BYTE 4 >BYTE NSSHI
  NSSLO 143 >BYTE 0 >BYTE 0 >BYTE NSSHI
  NSSLO 139 >BYTE 9 >BYTE 4 >BYTE 1 >BYTE 0 >BYTE NSSHI
  NSSLO 140 >BYTE 0 >BYTE 8 >BYTE 0 >BYTE 4 >BYTE
  1 >BYTE 0 >BYTE NSSHI
  NSSLO 8 >BYTE 2 >BYTE 1 >BYTE 2 >BYTE 1 >BYTE
  0 >BYTE 0 >BYTE 0 >BYTE 0 >BYTE NSSHI
  1 ;

\ Clear the IRQ before SetTx (DIO1 is a level), wait past
\ the air
\ time, then read TxDone out of the chip's own IRQ status.
: SEND ( -- ok )
  NSSLO 14 >BYTE 0 >BYTE
  165 >BYTE 49 >BYTE 50 >BYTE 51 >BYTE NSSHI
  NSSLO 2 >BYTE 255 >BYTE 255 >BYTE NSSHI
  NSSLO 131 >BYTE 15 >BYTE 0 >BYTE 0 >BYTE NSSHI
  150 MS
  NSSLO 18 >BYTE 0 >BYTE
  CLOCKLOW CLOCKLOW CLOCKLOW CLOCKLOW CLOCKLOW CLOCKLOW
  CLOCKLOW CLOCKLOW CLOCKLOW CLOCKLOW CLOCKLOW CLOCKLOW
  CLOCKLOW CLOCKLOW CLOCKLOW
  0 BITREAD NSSHI
  1 AND ;

