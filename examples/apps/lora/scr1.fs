\ scr1.fs - cross-phase-memory probe, phase 1. Writes 16 bytes
\ to the SX1262 buffer at offset 240, then CHAINs to scr2.
\ GUARDRAIL: R16 - no CREATE in a phase (its storage vanishes
\ on adopt), so the bytes and the offset are literals.
\ GUARDRAIL: R18 - the phase ends by chaining, or it can only
\ be left by reset. Pads: NSS 8, SCK 9, MOSI 10, MISO 11, BUSY
\ 13, in the ALIAS WINDOW.

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

\ WriteBuffer(0x0E) at offset 240, sixteen bytes 11 22 33 .. f0
\ 0f.
: W4A ( -- ) 17 >BYTE 34 >BYTE 51 >BYTE 68 >BYTE ;
: W4B ( -- ) 85 >BYTE 102 >BYTE 119 >BYTE 136 >BYTE ;
: W4C ( -- ) 153 >BYTE 170 >BYTE 187 >BYTE 204 >BYTE ;
: W4D ( -- ) 221 >BYTE 238 >BYTE 240 >BYTE 15 >BYTE ;
: W16 ( -- ) NSSLO 14 >BYTE 240 >BYTE
  W4A W4B W4C W4D NSSHI ;

\ GUARDRAIL: the phase ends by CHAINING (R18): a phase with no
\ return path can only be left by resetting the machine. 68 is
\ scr2's descriptor.
: SCR1 ( -- ) W16 68 CHAIN ;

