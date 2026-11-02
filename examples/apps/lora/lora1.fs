\ lora1.fs - SX1262 transmit driver in Forth.
\ Bit-banged SPI at the RTC GPIO registers: no C change,
\ no new primitives, 0 B of ULP pool.
\ Every line is under 63 B because that is what the device
\ input ring holds; longer lines are refused and never run.
\
\ ESP32-S3 RTCIO base 0x60008400; data fields start at bit 10,
\ so a halfword at +2 covers pins 6..21 - which is why W!/W@
\ are enough. Pins below 6 are not addressable this way.

8  CONSTANT LORA_NSS
9  CONSTANT LORA_SCK
10 CONSTANT LORA_MOSI
11 CONSTANT LORA_MISO
12 CONSTANT LORA_NRST
13 CONSTANT LORA_BUSY
14 CONSTANT LORA_DIO1

1610646534 CONSTANT LORA_SET  \ 0x60008406 OUT_W1TS  (set)
1610646538 CONSTANT LORA_CLR  \ 0x6000840A OUT_W1TC  (clear)
1610646566 CONSTANT LORA_IN   \ 0x60008426 IN
1610646546 CONSTANT LORA_EN   \ 0x60008412 ENABLE_W1TS
1610646660 CONSTANT LORA_PAD0 \ 0x60008484 RTC_IO_TOUCH_PAD0

\ 868.1 MHz = Hz*2^25/32e6 = 0x36 41 99 99 (54 65 153 153)

: ORW! ( bits addr -- ) DUP W@ ROT OR SWAP W! ;

: LORA! ( level pin -- )
  6 - 1 SWAP LSHIFT SWAP
  IF LORA_SET ELSE LORA_CLR THEN W! ;

: LORA@ ( pin -- level )
  6 - 1 SWAP LSHIFT LORA_IN W@ AND 0= 0= ;

\ pad mux: MUX_SEL bit 19 (upper half bit 3), FUN_IE bit 13
: LORA_MUX! ( pin -- ) 4 * LORA_PAD0 + DUP
  8 SWAP 2 + ORW!
  8192 SWAP ORW! ;

: LORA_OUT! ( pin -- ) 6 - 1 SWAP LSHIFT LORA_EN ORW! ;

: LORA_PINS
  8 LORA_MUX! 9 LORA_MUX! 10 LORA_MUX! 11 LORA_MUX!
  12 LORA_MUX! 13 LORA_MUX! 14 LORA_MUX!
  8 LORA_OUT! 9 LORA_OUT! 10 LORA_OUT! 12 LORA_OUT! ;

\ One bit of SPI mode 0: MOSI while SCK low, SCK high, low.
\ The byte loop is UNROLLED into eight of these: this dialect's
\ >R / R> leak two cells per call inside a calling word.
: LORA_SHIFT ( b -- b*2 )
  DUP 128 AND
  IF 1 LORA_MOSI LORA! ELSE 0 LORA_MOSI LORA! THEN
  1 LORA_SCK LORA!
  0 LORA_SCK LORA!
  2 * ;

: LORA>B ( b -- )
  LORA_SHIFT LORA_SHIFT LORA_SHIFT LORA_SHIFT
  LORA_SHIFT LORA_SHIFT LORA_SHIFT LORA_SHIFT
  DROP ;

\ one clock with MOSI low, returning MISO
: LORA_CLOCK ( -- bit )
  0 LORA_MOSI LORA!
  1 LORA_SCK LORA!
  LORA_MISO LORA@
  0 LORA_SCK LORA! ;

: LORA_SKIP8 LORA_CLOCK DROP LORA_CLOCK DROP LORA_CLOCK DROP
LORA_CLOCK DROP LORA_CLOCK DROP LORA_CLOCK DROP LORA_CLOCK
  DROP
  LORA_CLOCK DROP ;
: LORA_SKIP7 LORA_CLOCK DROP LORA_CLOCK DROP LORA_CLOCK DROP
LORA_CLOCK DROP LORA_CLOCK DROP LORA_CLOCK DROP LORA_CLOCK
  DROP ;

\ the 16th bit of the IRQ status word is TxDone (bit 0) and SPI
\ sends MSB first: skip the high byte plus 7, clock the last.
: LORA_IRQTX LORA_SKIP8 LORA_SKIP7 LORA_CLOCK ;

: LORA_BEG 0 LORA_NSS LORA! ;
: LORA_END 1 LORA_NSS LORA! ;

: LORA_CMD1 ( op arg -- )
  LORA_BEG SWAP LORA>B LORA>B LORA_END ;

\ BUSY is a LEVEL, polled with a bound: no unbounded wedges.
\ BUSY settle, with no loop on purpose: the chip zeroes the
\ data stack
\ per line and BEGIN/WHILE keep their compile-time markers
\ there, so a
\ loop split across lines loses them (ERR_STACK, measured on
\ the board).
\ A one-line loop is 96 B and a line is 63, so: settle 1 ms,
\ CHECK once.
\ BUSY still high means the command did not complete:
\ LORA_INIT returns
\ 0. Loud, never silent.
: LORA_WAITBUSY ( -- ok ) 1 MS LORA_BUSY LORA@ 0= ;

\ cold init: the sequence probe/lora runs on the hardware

: LORA_RESET ( -- ok )
  0 LORA_NRST LORA! 2 MS 1 LORA_NRST LORA! 5 MS LORA_WAITBUSY ;

\ cold init: the sequence probe/lora runs on the hardware
: LORA_INIT ( -- ok )
  LORA_PINS
  1 LORA_NSS LORA! 1 LORA_NRST LORA! 0 LORA_SCK LORA!
  LORA_RESET 0= IF 0 EXIT THEN
  128 0 LORA_CMD1
  150 1 LORA_CMD1
  LORA_BEG 151 LORA>B 2 LORA>B 0 LORA>B
  1 LORA>B 64 LORA>B LORA_END
  137 127 LORA_CMD1
  157 1 LORA_CMD1
  138 1 LORA_CMD1
  LORA_BEG 134 LORA>B 54 LORA>B 65 LORA>B
  153 LORA>B 153 LORA>B LORA_END
  LORA_BEG 152 LORA>B 215 LORA>B 219 LORA>B LORA_END
  LORA_BEG 149 LORA>B 2 LORA>B 2 LORA>B
  0 LORA>B 1 LORA>B LORA_END
  LORA_BEG 142 LORA>B 14 LORA>B 4 LORA>B LORA_END
  LORA_BEG 143 LORA>B 0 LORA>B 0 LORA>B LORA_END
  LORA_BEG 139 LORA>B 9 LORA>B 4 LORA>B
  1 LORA>B 0 LORA>B LORA_END
  LORA_BEG 140 LORA>B 0 LORA>B 8 LORA>B
  0 LORA>B 4 LORA>B 1 LORA>B 0 LORA>B LORA_END
  LORA_BEG 8 LORA>B 2 LORA>B 1 LORA>B
  2 LORA>B 1 LORA>B
  0 LORA>B 0 LORA>B 0 LORA>B 0 LORA>B LORA_END
  1 ;

\ 20 bytes: 0xA5 then 0x31..0x43. Unrolled, same reason as
\ above.
: LORA_FILL
  LORA_BEG 14 LORA>B 0 LORA>B
  165 LORA>B 49 LORA>B 50 LORA>B 51 LORA>B
  LORA_END ;

: LORA_SEND ( -- irq_ok )
  LORA_FILL
  \ clear the IRQ BEFORE SetTx: DIO1 is a LEVEL, so a stale
  \ TxDone makes the wait exit at once and reports a false sent
  LORA_BEG 2 LORA>B 255 LORA>B 255 LORA>B LORA_END
  LORA_BEG 131 LORA>B 15 LORA>B 0 LORA>B
  0 LORA>B LORA_END
\ air time is 185-196 ms (measured, docs/29 3): wait past it,
\ then
\ ASK THE CHIP. DIO1 polling would need a loop, and the IRQ
\ status is
  \ the stronger check anyway.
  150 MS
  LORA_BEG 18 LORA>B 0 LORA>B LORA_IRQTX LORA_END ;


: LORA_SLEEP 132 4 LORA_CMD1 ;
