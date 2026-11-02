\ scr2.fs - cross-phase-memory probe, phase 2. Adopted into a
\ FRESH dictionary; reads radio-buffer offset 240 and prints
\ the sixteen bytes. If they match scr1's pattern, the radio
\ buffer survives an ADOPT and an AES phase chain is possible
\ (cipher 1328 B vs 999 B window). GUARDRAIL: R16 - no CREATE
\ (a phase's storage vanishes on adopt), so the reads are
\ unrolled and there is no counter cell. GUARDRAIL: R11 - a
\ definition must fit ONE 92 B block; four 4-byte printers.
\ GUARDRAIL: R18 - returns by clearing NXT, so SWITCH unwinds
\ to the prompt. Pads: NSS 8, SCK 9, MOSI 10, MISO 11, BUSY 13,
\ ALIAS WINDOW.

: PIN! ( level pin -- )
  10 + 1 SWAP LSHIFT SWAP IF 41988 ELSE 41992 THEN ! ;
: PIN@ ( pin -- level )
  10 + 1 SWAP LSHIFT 42020 @ AND 0= 0= ;
: BUSY-LOW ( -- )
  200 BEGIN 1- 1 MS DUP 0= 13 PIN@ 0= OR UNTIL DROP ;
: NSSLO ( -- ) BUSY-LOW 0 8 PIN! ;
: BITOUT ( b -- b*2 )
  DUP 128 AND IF 1 10 PIN! ELSE 0 10 PIN! THEN
  1 9 PIN! 0 9 PIN! 2 * ;
: >BYTE ( b -- )
  BITOUT BITOUT BITOUT BITOUT
  BITOUT BITOUT BITOUT BITOUT DROP ;
: NSSHI ( -- ) 1 8 PIN! ;
: BITREAD ( b -- b' )
  2 * 1 9 PIN! 11 PIN@ 0 9 PIN! IF 1 + THEN ;
: RD-BYTE ( -- b ) 0 BITREAD BITREAD BITREAD BITREAD
  BITREAD BITREAD BITREAD BITREAD ;

: PB ( -- ) RD-BYTE . 32 EMIT ;
: PB4 ( -- ) PB PB PB PB ;
: R16 ( -- ) NSSLO 30 >BYTE 240 >BYTE RD-BYTE DROP
  PB4 PB4 PB4 PB4 NSSHI ;
: SCR2 ( -- ) R16 0 NXT ! ;

