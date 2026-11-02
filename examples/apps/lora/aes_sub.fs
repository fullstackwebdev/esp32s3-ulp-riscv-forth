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

\ the AES S-box: READ-ONLY, generated from the field definition
CREATE SBOX
  99 C, 124 C, 119 C, 123 C, 242 C, 107 C, 111 C, 197 C,
  48 C, 1 C, 103 C, 43 C, 254 C, 215 C, 171 C, 118 C,
  202 C, 130 C, 201 C, 125 C, 250 C, 89 C, 71 C, 240 C,
  173 C, 212 C, 162 C, 175 C, 156 C, 164 C, 114 C, 192 C,
  183 C, 253 C, 147 C, 38 C, 54 C, 63 C, 247 C, 204 C,
  52 C, 165 C, 229 C, 241 C, 113 C, 216 C, 49 C, 21 C,
  4 C, 199 C, 35 C, 195 C, 24 C, 150 C, 5 C, 154 C,
  7 C, 18 C, 128 C, 226 C, 235 C, 39 C, 178 C, 117 C,
  9 C, 131 C, 44 C, 26 C, 27 C, 110 C, 90 C, 160 C,
  82 C, 59 C, 214 C, 179 C, 41 C, 227 C, 47 C, 132 C,
  83 C, 209 C, 0 C, 237 C, 32 C, 252 C, 177 C, 91 C,
  106 C, 203 C, 190 C, 57 C, 74 C, 76 C, 88 C, 207 C,
  208 C, 239 C, 170 C, 251 C, 67 C, 77 C, 51 C, 133 C,
  69 C, 249 C, 2 C, 127 C, 80 C, 60 C, 159 C, 168 C,
  81 C, 163 C, 64 C, 143 C, 146 C, 157 C, 56 C, 245 C,
  188 C, 182 C, 218 C, 33 C, 16 C, 255 C, 243 C, 210 C,
  205 C, 12 C, 19 C, 236 C, 95 C, 151 C, 68 C, 23 C,
  196 C, 167 C, 126 C, 61 C, 100 C, 93 C, 25 C, 115 C,
  96 C, 129 C, 79 C, 220 C, 34 C, 42 C, 144 C, 136 C,
  70 C, 238 C, 184 C, 20 C, 222 C, 94 C, 11 C, 219 C,
  224 C, 50 C, 58 C, 10 C, 73 C, 6 C, 36 C, 92 C,
  194 C, 211 C, 172 C, 98 C, 145 C, 149 C, 228 C, 121 C,
  231 C, 200 C, 55 C, 109 C, 141 C, 213 C, 78 C, 169 C,
  108 C, 86 C, 244 C, 234 C, 101 C, 122 C, 174 C, 8 C,
  186 C, 120 C, 37 C, 46 C, 28 C, 166 C, 180 C, 198 C,
  232 C, 221 C, 116 C, 31 C, 75 C, 189 C, 139 C, 138 C,
  112 C, 62 C, 181 C, 102 C, 72 C, 3 C, 246 C, 14 C,
  97 C, 53 C, 87 C, 185 C, 134 C, 193 C, 29 C, 158 C,
  225 C, 248 C, 152 C, 17 C, 105 C, 217 C, 142 C, 148 C,
  155 C, 30 C, 135 C, 233 C, 206 C, 85 C, 40 C, 223 C,
  140 C, 161 C, 137 C, 13 C, 191 C, 230 C, 66 C, 104 C,
  65 C, 153 C, 45 C, 15 C, 176 C, 84 C, 187 C, 22 C,

: SB1 ( i -- i ) DUP ST + DUP C@ SBOX + C@ SWAP C! ;
: SBALL ( -- ) 0 BEGIN DUP 16 < WHILE SB1 1+ REPEAT DROP ;
: AES-SUB ( -- ) LS SBALL SS 84 CHAIN ;








