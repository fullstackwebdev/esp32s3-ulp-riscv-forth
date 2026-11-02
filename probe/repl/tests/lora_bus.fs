\ lora_bus.fs - self-contained SPI probe for the
\ SX1262.
\
\ Carries its own words: the shipping driver plus a
\ byte reader did not fit the pool (ERR_DICT at 7 923
\ of 7 932 B), and a probe that cannot load proves
\ nothing.
\
\ EVIDENCE: write a byte into the radio's RAM
\ (WriteBuffer 0x0E) and read it back (ReadBuffer
\ 0x1E). A dead bus reads 0, so only a copy of what we
\ wrote means the pads move for real. INIT returning 1
\ is NOT evidence: it reads BUSY, and a dead input
\ reads 0, the level INIT wants (R18).
\
\ GUARDRAIL: names are 6+ chars, unique. The 12-bit
\ dictionary hash collides on short names SILENTLY -
\ `: R1 ;` typed over a loaded driver made INIT stop
\ resolving, and nothing reports it.
\
\ GUARDRAIL: R21 counts the newline, so a line may
\ hold 62 chars. Longer lines are TRUNCATED, not
\ rejected, so split definitions and keep comments
\ short as well.
\
\ Pads per docs/29: NSS 8 SCK 9 MOSI 10 MISO 11 NRST
\ 12 BUSY 13. OUT data starts at bit 10, so a pad
\ number is not a bit number.

1610646532 CONSTANT BU-SET
1610646536 CONSTANT BU-CLR
1610646564 CONSTANT BU-IN

: BU-PIN ( level pad -- )
  10 + 1 SWAP LSHIFT SWAP IF BU-SET ELSE BU-CLR THEN ! ;

: BU-RED ( pad -- f )
  10 + 1 SWAP LSHIFT BU-IN AND 0= 0= ;

: BU-LO ( -- ) 0 8 BU-PIN ;
: BU-HI ( -- ) 1 8 BU-PIN ;

: BU-S ( b -- b*2 )
  DUP 128 AND IF 1 10 BU-PIN ELSE 0 10 BU-PIN THEN
  1 9 BU-PIN 0 9 BU-PIN 2 * ;

: BU-X8 ( b -- )
  BU-S BU-S BU-S BU-S BU-S BU-S BU-S BU-S DROP ;

: BU-BIT ( b -- b' )
  2 * 1 9 BU-PIN 11 BU-RED 0 9 BU-PIN IF 1 + THEN ;

: BU-4 ( b -- b' ) BU-BIT BU-BIT BU-BIT BU-BIT ;

: BU-RST ( -- ) 0 12 BU-PIN 2 MS 1 12 BU-PIN 5 MS ;

: BU-WRT ( b -- ) BU-LO 14 BU-X8 0 BU-X8 BU-X8 BU-HI ;

: BU-RD ( -- b ) BU-LO 30 BU-X8 0 BU-X8 0 BU-4 BU-4 BU-HI ;

: BU-STA ( -- b ) BU-LO 192 BU-X8 0 BU-4 BU-4 BU-HI ;
