\ aes_mc.fs - AES MixColumns on the state at buffer 224 (round
\ in 223). The last round has no MixColumns; the skip lives
\ here (aes_sub has no room). GUARDRAIL: TZ/ST/RB are SCRATCH,
\ freed with the phase. Pads: NSS 8, SCK 9, MOSI 10, MISO 11,
\ BUSY 13, ALIAS WINDOW.

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

\ SCRATCH: ST
\ SCRATCH: TZ
\ SCRATCH: RR
CREATE TZ
\ SCRATCH: TZ
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
CREATE ST
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
CREATE RB 0 C, 0 C, 0 C, 0 C,
\ SCRATCH: RB
: STZW ( b o -- ) ST + C! ;

: LB ( i -- i ) DUP RD-BYTE SWAP ST + C! ;
: LH ( -- ) NSSLO 30 >BYTE 240 >BYTE RD-BYTE DROP
  RD-BYTE 0 RB + C! ;
: LS ( -- ) LH 0 BEGIN DUP 16 < WHILE LB 1+ REPEAT DROP NSSHI ;
: SBF ( i -- i ) DUP ST + C@ >BYTE ;
: SH ( -- ) NSSLO 14 >BYTE 240 >BYTE 0 RB + C@ >BYTE ;
: SS SH 0 BEGIN DUP 16 < WHILE SBF 1+ REPEAT DROP NSSHI ;

: XT ( a -- 2a )
  DUP 128 AND IF 2 * 255 AND 27 XOR ELSE 2 * 255 AND THEN ;
: TZW ( b o -- ) TZ + C! ;
: TZ@ ( o -- b ) TZ + C@ ;
: LD4A ( b -- b ) DUP ST + C@ 0 TZW DUP 1+ ST + C@ 1 TZW ;
: LD4B ( b -- b ) DUP 2 + ST + C@ 2 TZW DUP 3 + ST + C@ 3 TZW ;
: TSUM ( -- b ) 0 TZ@ 1 TZ@ XOR 2 TZ@ XOR 3 TZ@ XOR ;
: AX ( i -- b ) 3 AND TZ@ ;
: MCO ( i -- b ) DUP AX OVER 1+ AX XOR
  XT SWAP AX XOR TSUM XOR ;
: MCW ( i -- ) DUP MCO SWAP 3 RB + C@ + STZW ;
: MC1 ( c -- ) 4 * DUP 3 RB + C! LD4A LD4B DROP ;
: MCW4 ( -- ) 0 MCW 1 MCW 2 MCW 3 MCW ;
: MC0 ( -- ) 0 MC1 MCW4 1 MC1 MCW4 2 MC1 MCW4 3 MC1 MCW4 ;
: MCGO ( -- ) 0 RB + C@ 10 < IF MC0 THEN ;
: AES-MC ( -- ) LS MCGO SS 112 CHAIN ;








