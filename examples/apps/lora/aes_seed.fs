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
  0 C, 0 C, 1 C, 254 C, 202 C, 0 C, 0 C, 0 C,
  0 C, 10 C, 10 C, 10 C, 10 C, 0 C, 0 C, 0 C,
  0 C, 0 C,
: SND ( i -- i ) DUP CT + C@ >BYTE ;
: SND18 ( -- ) NSSLO 14 >BYTE 223 >BYTE
  0 BEGIN DUP 18 < WHILE SND 1+ REPEAT DROP NSSHI ;
: AES-SEED ( -- ) SND18 100 CHAIN ;


