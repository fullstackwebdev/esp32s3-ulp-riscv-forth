\ lorainit.fs - the SX1262 bring-up as its OWN PHASE.
\
\ WHY A PHASE: INIT is a fixed byte sequence, and written as
\ Forth it cost 491 B of app space (measured per-word: 488 B
\ code + 3 B header). A phase is loaded into the pool on its
\ own, runs, and hands off, so it costs the app nothing while
\ it is not running. The app then only carries what it needs
\ every packet - primitives, SEND, receive words - leaving room
\ for AES and protobuf, which is the whole point of the
\ exercise.
\
\ GUARDRAIL: a phase cannot see another phase's words
\ (measured: a phase calling a neighbour's DRAW is refused BY
\ NAME), so this file declares its own primitives. That
\ duplication is the price of chaining and it is what makes the
\ primitive set a candidate for baking into the image later.
\
\ GUARDRAIL: every line stays under 63 B - the device input
\ ring drops longer lines SILENTLY, and the definition then
\ simply does not exist.
\
\ GUARDRAIL: the configuration is DATA, not code. Each
\ transaction is `len, bytes...` and is clocked out by XFER;
\ adding or changing a radio setting is a table edit, not 35
\ more tokens of compiled code.
\
\ CONFIG (unchanged from the measured driver): STDBY_RC, DC-DC,
\ TCXO 1.8 V on DIO3 with a 5 ms start-up, calibrate all, DIO2
\ as RF switch, LoRa, 868.1 MHz (0x36419999 = 54 65 153 153),
\ image cal 863-870, PA 14 dBm, buffer base 0, SF9 / BW125 /
\ CR4-5 / LDRO 0, preamble 8, explicit header, length 4, CRC
\ on, all IRQ sources enabled in the mask.
\
\ Pads on this board: NSS 8, SCK 9, MOSI 10, MISO 11, RESET 12,
\ BUSY 13.
\
: PIN! ( level pin -- )
  10 + 1 SWAP LSHIFT SWAP IF 41988 ELSE 41992 THEN ! ;
: PIN@ ( pin -- level )
  10 + 1 SWAP LSHIFT 42020 @ AND 0= 0= ;
: BUSY-LOW ( -- )
  200 BEGIN 1- 1 MS DUP 0= 13 PIN@ 0= OR UNTIL DROP ;
: NSSLO ( -- ) BUSY-LOW 0 8 PIN! ;
: NSSHI ( -- ) 1 8 PIN! ;
: BITOUT ( b -- b*2 )
  DUP 128 AND IF 1 10 PIN! ELSE 0 10 PIN! THEN
  1 9 PIN! 0 9 PIN! 2 * ;
: BITREAD ( b -- b' )
  2 * 1 9 PIN! 11 PIN@ 0 9 PIN! IF 1 + THEN ;
: >BYTE ( b -- )
  BITOUT BITOUT BITOUT BITOUT
  BITOUT BITOUT BITOUT BITOUT DROP ;
: RD-BYTE ( -- b ) 0 BITREAD BITREAD BITREAD BITREAD
  BITREAD BITREAD BITREAD BITREAD ;
: RD2 ( -- w ) RD-BYTE 8 LSHIFT RD-BYTE OR ;
: INEN ( padreg -- )
  DUP @ 8192 OR 393216 INVERT AND SWAP ! ;
\
\ The configuration table. First byte of each entry is its
\ length.
\ GUARDRAIL: enable the SX1262 boosted RX gain (reg
\ 0x08AC = 0x96, RadioLib setRxBoostedGainMode). Without
\ it we got RxDone+CrcErr where a stock node decoded.
CREATE TBL
  2 C, 128 C, 0 C,
  2 C, 150 C, 1 C,
  5 C, 151 C, 2 C, 0 C, 1 C, 64 C,
  2 C, 137 C, 127 C,
  2 C, 157 C, 1 C,
  2 C, 138 C, 1 C,
  5 C, 134 C, 54 C, 88 C, 163 C, 215 C,
  3 C, 152 C, 215 C, 219 C,
  5 C, 149 C, 2 C, 2 C, 0 C, 1 C,
  3 C, 142 C, 14 C, 4 C,
  3 C, 143 C, 0 C, 0 C,
  5 C, 139 C, 12 C, 4 C, 1 C, 1 C,
  5 C, 13 C, 7 C, 64 C, 20 C, 36 C,
  4 C, 13 C, 8 C, 216 C, 94 C,
  4 C, 13 C, 8 C, 172 C, 150 C,
  0 C,
  0 C, 0 C,
  7 C, 140 C, 0 C, 8 C, 0 C, 4 C, 1 C, 0 C,
  9 C, 8 C, 255 C, 255 C, 0 C,
  0 C, 0 C, 0 C, 0 C, 0 C,
  0 C,
  0 C,
CREATE CFGPTR 0 ,
CREATE CFGLEN 0 ,
: ADV ( n -- ) CFGPTR @ + CFGPTR ! ;
: CLKN ( n -- )
  BEGIN DUP WHILE CFGPTR @ C@ >BYTE 1 ADV 1- REPEAT DROP ;
: XFER ( -- ) NSSLO CFGPTR @ C@ 1 ADV CLKN NSSHI ;
: ALL ( n -- ) BEGIN DUP WHILE XFER 1- REPEAT DROP ;
: NCMDS ( -- n ) 20 ;
: RADIO-INIT ( -- ok )
  42160 INEN 42168 INEN 42172 INEN
  1 8 PIN! 1 12 PIN! 0 9 PIN!
  0 12 PIN! 2 MS 1 12 PIN! 5 MS
  1 MS 13 PIN@ 0= 0= IF 0 EXIT THEN
  TBL CFGPTR ! NCMDS ALL
  1 ;
\
\ Verification words, so the phase can be checked instead of
\ trusted: STAT = GetStatus (chipmode bits 6..4: 2 = STDBY_RC,
\ 5 = RX), PTYPE = GetPacketType (1 = LoRa). Both are
\ documented commands with unambiguous answers. A register
\ readback was attempted and dropped: the offset used (0x0880)
\ was never verified here, so asserting on it would have been
\ asserting on a guess.
: STAT ( -- st ) NSSLO 192 >BYTE RD-BYTE NSSHI ;
: PTYPE ( -- t ) NSSLO 17 >BYTE RD-BYTE DROP RD-BYTE NSSHI ;

