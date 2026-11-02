\ aes_out.fs - PHASE: the chain's LAST hop: encrypt, frame, transmit.
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
  8 C, 128 C, 2 C, 18 C, 6 C, 104 C, 101 C, 108 C,
  108 C, 111 C, 33 C, 0 C, 0 C, 0 C, 0 C, 0 C,
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
: PB2 ( -- ) NSSLO 30 >BYTE 224 >BYTE RD-BYTE DROP ;
: INTO ( -- ) PB2 0 BEGIN DUP 11 < WHILE PULX 1+ REPEAT DROP NSSHI ;
: OUTB ( i -- i ) DUP SBC + C@ >BYTE ;
: PUT ( -- ) NSSLO 14 >BYTE 16 >BYTE
  0 BEGIN DUP 11 < WHILE OUTB 1+ REPEAT DROP NSSHI ;
: ADV ( n -- ) CFGPTR @ + CFGPTR ! ;
: CLKN ( n -- ) BEGIN DUP WHILE CFGPTR @ C@ >BYTE 1 ADV 1- REPEAT DROP ;
: ALL ( n -- ) BEGIN DUP WHILE NSSLO CFGPTR @ C@ 1 ADV CLKN NSSHI 1- REPEAT DROP ;
: IQ ( -- w ) NSSLO 18 >BYTE 0 >BYTE RD-BYTE 8 LSHIFT RD-BYTE OR NSSHI ;
: FRMB ( -- ) FRM CFGPTR ! NSSLO 14 >BYTE 0 >BYTE 16 CLKN NSSHI ;
: TX ( -- ) NSSLO 131 >BYTE 0 >BYTE 0 >BYTE 0 >BYTE NSSHI ;
: WAITX ( -- ) 2000 BEGIN 1- DUP 0= IF DROP EXIT THEN IQ 1 AND UNTIL DROP ;
: AES-OUT ( -- ) INTO PUT FRMB TX WAITX 0 NXT ! ;