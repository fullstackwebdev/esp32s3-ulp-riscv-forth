\ aes_ark.fs - AES AddRoundKey on the state at buffer 224 (round in 240).
\ W is the 44 round-key words for the LongFast PSK (constant data).
\ GUARDRAIL: TZ/ST/RB are SCRATCH, freed with the phase.
\ Pads: NSS 8, SCK 9, MOSI 10, MISO 11, BUSY 13, ALIAS WINDOW.

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

\ the 44 round keys for the LongFast PSK
CREATE W
  212 C, 241 C, 187 C, 58 C, 32 C, 41 C, 7 C, 89 C,
  240 C, 188 C, 255 C, 171 C, 207 C, 78 C, 105 C, 1 C,
  250 C, 8 C, 199 C, 176 C, 218 C, 33 C, 192 C, 233 C,
  42 C, 157 C, 63 C, 66 C, 229 C, 211 C, 86 C, 67 C,
  158 C, 185 C, 221 C, 105 C, 68 C, 152 C, 29 C, 128 C,
  110 C, 5 C, 34 C, 194 C, 139 C, 214 C, 116 C, 129 C,
  108 C, 43 C, 209 C, 84 C, 40 C, 179 C, 204 C, 212 C,
  70 C, 182 C, 238 C, 22 C, 205 C, 96 C, 154 C, 151 C,
  180 C, 147 C, 89 C, 233 C, 156 C, 32 C, 149 C, 61 C,
  218 C, 150 C, 123 C, 43 C, 23 C, 246 C, 225 C, 188 C,
  230 C, 107 C, 60 C, 25 C, 122 C, 75 C, 169 C, 36 C,
  160 C, 221 C, 210 C, 15 C, 183 C, 43 C, 51 C, 179 C,
  55 C, 168 C, 81 C, 176 C, 77 C, 227 C, 248 C, 148 C,
  237 C, 62 C, 42 C, 155 C, 90 C, 21 C, 25 C, 40 C,
  46 C, 124 C, 101 C, 14 C, 99 C, 159 C, 157 C, 154 C,
  142 C, 161 C, 183 C, 1 C, 212 C, 180 C, 174 C, 41 C,
  35 C, 152 C, 192 C, 70 C, 64 C, 7 C, 93 C, 220 C,
  206 C, 166 C, 234 C, 221 C, 26 C, 18 C, 68 C, 244 C,
  241 C, 131 C, 127 C, 228 C, 177 C, 132 C, 34 C, 56 C,
  127 C, 34 C, 200 C, 229 C, 101 C, 48 C, 140 C, 17 C,
  195 C, 231 C, 253 C, 169 C, 114 C, 99 C, 223 C, 145 C,
  13 C, 65 C, 23 C, 116 C, 104 C, 113 C, 155 C, 101 C,

\ SCRATCH: ST
\ SCRATCH: TZ
\ SCRATCH: RR
CREATE TZ
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
CREATE ST
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
CREATE RB 0 C, 0 C,
\ SCRATCH: RB

: LB ( i -- i ) DUP RD-BYTE SWAP ST + C! ;
: LH ( -- ) NSSLO 30 >BYTE 240 >BYTE RD-BYTE DROP
  RD-BYTE 0 RB + C! ;
: LS ( -- ) LH 0 BEGIN DUP 16 < WHILE LB 1+ REPEAT DROP NSSHI ;
: SBF ( i -- i ) DUP ST + C@ >BYTE ;
: SH ( -- ) NSSLO 14 >BYTE 240 >BYTE 0 RB + C@ >BYTE ;
: SS ( -- ) SH 0 BEGIN DUP 16 < WHILE SBF 1+ REPEAT DROP NSSHI ;

: ARB ( i -- i ) DUP DUP ST + C@ OVER RB C@ 16 * + W + C@ XOR SWAP ST + C! ;
: ARK ( -- ) 0 BEGIN DUP 16 < WHILE ARB 1+ REPEAT
  DROP ;

: RINC ( -- ) 0 RB + C@ 1+ 0 RB + C! ;
: NXT2 ( r -- ) 11 < IF 88 CHAIN ELSE 72 CHAIN THEN ;
: AES-ARK ( -- ) LS ARK RINC SS 0 RB + C@ NXT2 ;

