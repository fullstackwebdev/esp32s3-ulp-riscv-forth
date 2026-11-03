\ aes_out.fs - PHASE: the chain's LAST hop, once PER 16-byte block.
\ XORs this block's keystream with its slice of the MeshPacket and
\ stores it at 16+16b, then either patches the CTR counter (last four
\ nonce bytes, big-endian) and chains back to AES-ARK, or writes the
\ 16-byte header and transmits. Pads: NSS 8, SCK 9, MOSI 10, MISO 11.
: PIN! ( level pin -- )
  10 + 1 SWAP LSHIFT SWAP IF 41988 ELSE 41992 THEN ! ;
: PIN@ ( pin -- level )
  10 + 1 SWAP LSHIFT 42020 @ AND 0= 0= ;
: NSSLO ( -- ) 1 MS 0 8 PIN! ;
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
  13 C, 36 C, 190 C, 234 C, 2 C, 21 C, 255 C, 255 C,
  255 C, 255 C, 34 C, 15 C, 8 C, 1 C, 18 C, 11 C,
  104 C, 105 C, 32 C, 102 C, 114 C, 111 C, 109 C, 32 C,
  117 C, 108 C, 112 C, 53 C, 74 C, 59 C, 44 C, 29 C,
CREATE SBC
\ SCRATCH: SBC
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
CREATE FRM
  255 C, 255 C, 255 C, 255 C,
  36 C, 190 C, 234 C, 2 C,
  74 C, 59 C, 44 C, 29 C,
  99 C, 8 C, 0 C, 0 C,
CREATE B16 0 C, 0 C,
\ SCRATCH: B16
CREATE CFGPTR 0 ,
\ SCRATCH: CFGPTR

: ADV ( n -- ) CFGPTR @ + CFGPTR ! ;
: CLKN ( n -- ) BEGIN DUP WHILE CFGPTR @ C@ >BYTE 1 ADV 1- REPEAT DROP ;
: RDB ( -- b ) NSSLO 30 >BYTE 48 >BYTE RD-BYTE DROP RD-BYTE NSSHI ;
: KC ( i -- i ) DUP RD-BYTE OVER B16 C@ + PL + C@ XOR SWAP SBC + C! ;
: KXO ( -- ) NSSLO 30 >BYTE 224 >BYTE RD-BYTE DROP ;
: KX ( b -- ) 4 LSHIFT B16 C! KXO
  0 BEGIN DUP 16 < WHILE KC 1+ REPEAT DROP NSSHI ;
: OUTB ( i -- i ) DUP SBC + C@ >BYTE ;
: PUTO ( n -- ) NSSLO 14 >BYTE >BYTE ;
: PUT ( b -- ) 4 LSHIFT 16 + PUTO
  0 BEGIN DUP 16 < WHILE OUTB 1+ REPEAT DROP NSSHI ;
: PCTR ( b -- ) NSSLO 14 >BYTE 236 >BYTE 0 >BYTE 0 >BYTE 0 >BYTE >BYTE 0 >BYTE NSSHI ;
: FRMB ( -- ) FRM CFGPTR ! NSSLO 14 >BYTE 0 >BYTE 16 CLKN NSSHI ;
: IQ ( -- w ) NSSLO 18 >BYTE 0 >BYTE RD-BYTE 8 LSHIFT RD-BYTE OR NSSHI ;
: TX ( -- ) NSSLO 131 >BYTE 0 >BYTE 0 >BYTE 0 >BYTE NSSHI ;
: WAITX ( -- ) 2000 BEGIN 1- DUP 0= IF DROP EXIT THEN IQ 1 AND UNTIL DROP ;
: SETB ( n -- ) NSSLO 14 >BYTE 48 >BYTE >BYTE NSSHI ;
: NEXTB ( b -- b ) 1+ DUP SETB DUP 2 < IF DUP PCTR 112 CHAIN THEN ;
: NXTC ( b -- ) NXT @ IF DROP EXIT THEN DROP FRMB TX WAITX 0 NXT ! ;
: AES-OUT ( -- ) RDB DUP KX DUP PUT NEXTB NXTC ;
