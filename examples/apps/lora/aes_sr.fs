\ aes_sr.fs - PHASE: AES ShiftRows on the state at buffer 224
\ (round in 223). A separate phase because SubBytes+ShiftRows
\ together came to 1045 B against the 999 B window. Rows are
\ contiguous with stride 4, so each row rotates with ONE byte
\ of temp: six R4 calls do the whole transform. GUARDRAIL:
\ TZ/ST/RB are SCRATCH, freed with the phase. Pads: NSS 8, SCK
\ 9, MOSI 10, MISO 11, BUSY 13, ALIAS WINDOW.

\ aes_sub.fs - AES SubBytes + ShiftRows on the state at buffer
\ 224. One phase of the cipher chain; state travels in the
\ radio buffer. GUARDRAIL: SBOX is read-only (phase image);
\ ST/TZ are SCRATCH. Pads: NSS 8, SCK 9, MOSI 10, MISO 11, BUSY
\ 13, ALIAS WINDOW.

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

\ SCRATCH: TZ
CREATE TZ 0 C, 0 C,
: TZW ( b o -- ) TZ + C! ;
: TZ@ ( o -- b ) TZ + C@ ;
\ SCRATCH: ST SCRATCH: TZ
CREATE ST
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
: LB ( i -- i ) DUP RD-BYTE SWAP ST + C! ;
: LH ( -- ) NSSLO 30 >BYTE 224 >BYTE RD-BYTE DROP ;
: LS ( -- ) LH 0 BEGIN DUP 16 < WHILE LB 1+ REPEAT DROP
  NSSHI ;
: SBF ( i -- i ) DUP ST + C@ >BYTE ;
: SH ( -- ) NSSLO 14 >BYTE 224 >BYTE ;
: SS ( -- ) SH 0 BEGIN DUP 16 < WHILE SBF 1+ REPEAT DROP
  NSSHI ;

: ST@ ( o -- b ) ST + C@ ;
: STZW ( b o -- ) ST + C! ;
: R4A ( o -- o ) DUP 4 + ST@ OVER STZW
  DUP 8 + ST@ OVER 4 + STZW ;
: R4B ( o -- ) DUP 12 + ST@ OVER 8 + STZW
  12 + 0 TZ@ SWAP STZW ;
: ROT4 ( o -- ) DUP ST@ 0 TZW R4A R4B ;
: SRALL ( -- ) 1 ROT4 2 ROT4 2 ROT4
  3 ROT4 3 ROT4 3 ROT4 ;

: AES-SR ( -- ) LS SRALL SS 92 CHAIN ;


