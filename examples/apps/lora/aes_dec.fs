\ aes_dec.fs - PHASE: the chain's LAST hop on the RECEIVE side: the
\ state is the keystream, XOR it with the ciphertext that arrived on
\ the air and print the recovered protobuf. Same chain, same key.
\ Reads the state from 224 into RAM, XORs it with the protobuf, and
\ only THEN resets and configures the radio (a reset wipes the
\ SX1262's 256-byte buffer, which is where the state lived), writes
\ 16 header bytes at 0 and 11 ciphertext bytes at 16, and transmits
\ 27 bytes. Pads: NSS 8, SCK 9, MOSI 10, MISO 11, BUSY 13, ALIAS.

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
CREATE PL
  234 C, 178 C, 176 C, 13 C, 64 C, 109 C, 87 C, 142 C,
  159 C, 182 C, 33 C, 0 C, 0 C, 0 C, 0 C, 0 C,
CREATE SBC
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
  0 C, 0 C, 0 C, 0 C,
CREATE FRM
  255 C, 255 C, 255 C, 255 C,
  10 C, 10 C, 10 C, 10 C,
  202 C, 254 C, 1 C, 0 C,
  0 C, 8 C, 0 C, 0 C,
CREATE CFGPTR 0 ,

: PULX ( i -- i ) DUP RD-BYTE OVER PL + C@ XOR SWAP SBC + C! ;
: PB ( -- ) RD-BYTE . 32 EMIT ;
: OPEN2 ( o -- ) NSSLO 30 >BYTE >BYTE RD-BYTE DROP ;
: PB2 ( -- ) 224 OPEN2 ;
: INTO ( -- ) PB2 0 BEGIN DUP 11 < WHILE PULX 1+ REPEAT DROP NSSHI ;
: OUTB ( i -- i ) DUP SBC + C@ >BYTE ;
: PUT ( -- ) NSSLO 14 >BYTE 16 >BYTE
  0 BEGIN DUP 11 < WHILE OUTB 1+ REPEAT DROP NSSHI ;
: SHOW ( -- ) 16 OPEN2 0 BEGIN DUP 11 < WHILE PB 1+ REPEAT DROP NSSHI ;
: AES-DEC ( -- ) INTO PUT SHOW 0 NXT ! ;