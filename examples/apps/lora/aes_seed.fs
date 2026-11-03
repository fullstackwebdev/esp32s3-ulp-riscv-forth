\ aes_seed.fs - PHASE: put the CTR counter block and round 0 in
\ the SX1262 buffer (offset 223) and start the cipher chain at
\ AES-ARK (100). The nonce is Meshtastic's: packetId u64 LE,
\ from u32 LE, four zeros. On a device these bytes come from
\ the packet header being sent; baked here so the chain can be
\ tested on its own. GUARDRAIL: 17 data bytes is ODD - the
\ trailing pad keeps HERE even (R28). Pads: NSS 8, SCK 9, MOSI
\ 10, MISO 11, BUSY 13, ALIAS WINDOW.

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
: >BYTE ( b -- )
  BITOUT BITOUT BITOUT BITOUT
  BITOUT BITOUT BITOUT BITOUT DROP ;
CREATE CT
  74 C, 59 C, 44 C, 29 C, 0 C, 0 C, 0 C, 0 C,
  36 C, 190 C, 234 C, 2 C, 0 C, 0 C, 0 C, 0 C,
  0 C, 0 C,
: SND ( i -- i ) DUP CT + C@ >BYTE ;
: SND18 ( -- ) NSSLO 14 >BYTE 224 >BYTE
  0 BEGIN DUP 18 < WHILE SND 1+ REPEAT DROP NSSHI ;
CREATE CFGG 0 ,
\ SCRATCH: CFGG
CREATE TBL
  2 C, 128 C, 0 C,
  2 C, 150 C, 1 C,
  2 C, 8 C, 56 C,
  0 C,
  5 C, 151 C, 2 C, 0 C, 1 C, 64 C,
  2 C, 137 C, 127 C,
  2 C, 157 C, 1 C,
  2 C, 138 C, 1 C,
  5 C, 134 C, 54 C, 87 C, 174 C, 20 C,
  3 C, 152 C, 215 C, 219 C,
  5 C, 149 C, 2 C, 2 C, 0 C, 1 C,
  3 C, 142 C, 14 C, 4 C,
  3 C, 143 C, 0 C, 0 C,
  5 C, 139 C, 11 C, 5 C, 1 C, 0 C,
  5 C, 13 C, 7 C, 64 C, 20 C, 36 C,
  4 C, 13 C, 8 C, 216 C, 94 C,
  0 C, 0 C,
  7 C, 140 C, 0 C, 16 C, 0 C, 48 C, 1 C, 0 C,
  9 C, 8 C, 255 C, 255 C, 0 C,
  0 C, 0 C, 0 C, 0 C, 0 C,
  0 C, 0 C,
: INEN ( r -- ) DUP @ 8192 OR SWAP ! ;
: ADV ( n -- ) CFGG @ + CFGG ! ;
: CLKN ( n -- ) BEGIN DUP WHILE CFGG @ C@ >BYTE 1 ADV 1- REPEAT DROP ;
: ALL ( n -- ) BEGIN DUP WHILE NSSLO CFGG @ C@ 1 ADV CLKN NSSHI 1- REPEAT DROP ;
: RST ( -- ) 1 8 PIN! 1 12 PIN! 0 9 PIN! 0 12 PIN! 2 MS 1 12 PIN! 5 MS ;
: CFG ( -- ) 42160 INEN 42168 INEN 42172 INEN RST 1 MS TBL CFGG ! 20 ALL ;
: CLRB ( -- ) NSSLO 14 >BYTE 48 >BYTE 0 >BYTE NSSHI ;
: AES-SEED ( -- ) CFG CLRB SND18 112 CHAIN ;


