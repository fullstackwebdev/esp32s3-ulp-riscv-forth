\ lora1.fs - SX1262 transmit driver in FORTH, bit-banged with GPIO! / GPIO@ alone.
\
\ No new primitives. This machine already has GPIO! ( level pin -- ), GPIO@ ( pin -- ),
\ MS, and the comparisons; everything the C driver in probe/lora does with registers is
\ done here with those. The Forth question was about BYTES, not speed: docs/29 sec 6 -
\ 95 % of the ULP's awake window is the packet on air, so the bus MHz does not matter.
\
\ The interpreter IS the delay. At ~6 tokens per bit this runs ~30-40 kHz, well under the
\ 144.6 kHz the C HAL measured (docs/29 sec 2) and far under what the radio cares about.
\
\ GUARDRAIL: no VARIABLE and no CREATE here. A phase may not own state (linter R16), so the
\ SPI temporaries live on the RETURN stack and the payload bytes are computed as they are sent.
\ The first version used VARIABLE/CREATE and the machine answered VARIABLE? at line 23.

8  CONSTANT LORA_NSS
9  CONSTANT LORA_SCK
10 CONSTANT LORA_MOSI
11 CONSTANT LORA_MISO
12 CONSTANT LORA_NRST
13 CONSTANT LORA_BUSY
14 CONSTANT LORA_DIO1

\ 868.1 MHz -> register Hz*2^25/32e6 = 910268825 = 0x36 41 99 99, pushed byte by byte below
\ (54 65 153 153). Computed from the formula, never recalled.

: LORA! ( v pin -- ) GPIO! ;
: LORA@ ( pin -- v ) GPIO@ ;

\ One byte, SPI mode 0, MSB first: MOSI while SCK low, SCK high, sample MISO, SCK low.
\ GUARDRAIL: no >R / R> here, and no counter in the bit path. This dialect's return stack
\ leaked: a byte loop built on >R ... R> left TWO extra cells per byte - measured on the
\ host, `7 9 LORA_SPIX . . .` printed three numbers - which shifted every later argument.
\ The bit loop is UNROLLED into eight LORA_SHIFT steps, each ( b -- b*2 ): the stack shape
\ never changes and it is the faster shape too (docs/27: unroll the bit loop).
: LORA_SHIFT ( b -- b*2 )
  DUP 128 AND IF 1 LORA_MOSI LORA! ELSE 0 LORA_MOSI LORA! THEN
  1 LORA_SCK LORA!
  0 LORA_SCK LORA!
  2 * ;

: LORA>B ( b -- )
  LORA_SHIFT LORA_SHIFT LORA_SHIFT LORA_SHIFT
  LORA_SHIFT LORA_SHIFT LORA_SHIFT LORA_SHIFT
  DROP ;

\ One clock with MOSI low, returning MISO. Only the LAST bit of a word is ever needed here
\ (TxDone is bit 0 of the 16-bit IRQ status, and SPI sends MSB first), so nothing accumulates.
: LORA_CLOCK ( -- bit )
  0 LORA_MOSI LORA!
  1 LORA_SCK LORA!
  LORA_MISO LORA@
  0 LORA_SCK LORA!
  ;

: LORA_SKIP8 ( -- ) 0 BEGIN DUP 8 < WHILE LORA_CLOCK DROP 1+ REPEAT DROP ;
: LORA_SKIP7 ( -- ) 0 BEGIN DUP 7 < WHILE LORA_CLOCK DROP 1+ REPEAT DROP ;

\ The 16th bit of the IRQ status word is bit 0 = TxDone, and SPI sends MSB first, so: skip the
\ high byte, skip 7 bits of the low byte, and the next clock returns the flag we want.
: LORA_IRQTX ( -- txdone ) LORA_SKIP8 LORA_SKIP7 LORA_CLOCK ;

: LORA_BEG ( -- ) 0 LORA_NSS LORA! ;
: LORA_END ( -- ) 1 LORA_NSS LORA! ;

\ the class this project bans. 200000 iterations is tens of ms. DIO1 below uses 0= to
\ the class this project bans. 200000 iterations is tens of ms. DIO1 below uses 0= to
\ the bound and reported failure, and the host trace showed a reset pulse and nothing else. The
\ DIO1 wait below legitimately uses `0=` because it is waiting for a line to come UP.
: LORA_WAITBUSY ( -- ok )
  200000
  BEGIN
    LORA_BUSY LORA@
  WHILE
    1-
    DUP 0=
    IF DROP 0 EXIT THEN
  REPEAT
  DROP 1 ;

: LORA_CMD1 ( op arg -- ) LORA_BEG SWAP LORA>B LORA>B LORA_END ;

\ GUARDRAIL: the pin constant is LORA_NRST, NOT LORA_RESET. It was LORA_RESET once, which made
\ `1 LORA_RESET LORA!` call THIS word recursively - the dictionary had one name for two
\ meanings, the machine answered `error` with no name, and this project's own rule R15
\ ("the same name can be two words") was the answer. A pin constant and an action never
\ share a name.
: LORA_RESET ( -- ok )
  0 LORA_NRST LORA! 2 MS 1 LORA_NRST LORA! 5 MS LORA_WAITBUSY ;

\ --- cold init: the sequence probe/lora uses, the one that gave TxDone on the board -------
: LORA_INIT ( -- ok )
  1 LORA_NSS LORA! 1 LORA_NRST LORA! 0 LORA_SCK LORA!
  LORA_RESET 0= IF 0 EXIT THEN
  128 0 LORA_CMD1                     \ SetStandby STDBY_RC
  150 1 LORA_CMD1                     \ SetRegulatorMode: DC-DC
  LORA_BEG 151 LORA>B 2 LORA>B 0 LORA>B 1 LORA>B 64 LORA>B LORA_END
  \ ^ SetDIO3AsTCXOCtrl: 1.8 V, 5 ms start-up (0x02 0x00 0x01 0x40)
  137 127 LORA_CMD1                   \ CalibrateImage: all blocks
  157 1 LORA_CMD1                     \ SetDIO2AsRFSwitch
  138 1 LORA_CMD1                     \ SetPacketType: LoRa
  LORA_BEG 134 LORA>B 54 LORA>B 65 LORA>B 153 LORA>B 153 LORA>B LORA_END
  \ ^ SetRfFrequency 868.1 MHz
  LORA_BEG 152 LORA>B 215 LORA>B 219 LORA>B LORA_END
  \ ^ CalibrateImage for 863-870 MHz
  LORA_BEG 149 LORA>B 2 LORA>B 2 LORA>B 0 LORA>B 1 LORA>B LORA_END
  \ ^ SetPaConfig for +14 dBm
  LORA_BEG 142 LORA>B 14 LORA>B 4 LORA>B LORA_END
  \ ^ SetTxParams: 14 dBm, 200 us ramp
  LORA_BEG 143 LORA>B 0 LORA>B 0 LORA>B LORA_END
  \ ^ SetBufferBaseAddress 0, 0
  LORA_BEG 139 LORA>B 9 LORA>B 4 LORA>B 1 LORA>B 0 LORA>B LORA_END
  \ ^ SetModulationParams: SF9, BW 125 kHz, CR 4/5, LDRO off
  LORA_BEG 140 LORA>B 0 LORA>B 8 LORA>B 0 LORA>B 20 LORA>B 1 LORA>B 0 LORA>B LORA_END
  \ ^ SetPacketParams: preamble 0x0008 (a 16-BIT field - the leading 0 was missing once and the
\   packet length landed where the CRC type belongs), explicit header, 20 B, CRC on, std IQ
  LORA_BEG 8 LORA>B 2 LORA>B 1 LORA>B 2 LORA>B 1 LORA>B 0 LORA>B 0 LORA>B
          0 LORA>B 0 LORA>B LORA_END
  \ ^ SetDioIrqParams: TxDone|Timeout -> DIO1
  1 ;

\ --- one transmit ----------------------------------------------------------------------
: LORA_FILL ( -- )
  \ 20 bytes straight into the radio's TX buffer: marker, then a recognisable ramp.
  \ GUARDRAIL: the byte is computed on top of the index, never instead of it - the first
  \ version consumed the index in the IF branch and the following 1+ underflowed.
  \ consumed the index in the IF branch and the following 1+ underflowed (ERR_STACK).
  LORA_BEG 14 LORA>B 0 LORA>B
  0 BEGIN DUP 20 < WHILE
    DUP 0= IF 165 ELSE DUP 48 + THEN
    LORA>B
    1+
  REPEAT DROP
  LORA_END ;

\ GUARDRAIL: this file was once patched by LINE INDEX, the splice put the GetIrqStatus line
\ inside LORA_SEND and ended the definition early - the machine then said only "error", with
\ no name, while the trace still looked plausible. Rewrite a region whole, never by index.
: LORA_SEND ( -- irq_ok )
  LORA_FILL
  \ GUARDRAIL: clear the IRQ BEFORE SetTx. DIO1 is a LEVEL, so a leftover TxDone makes the wait
\ no name, while the trace looked plausible. Rewrite a region whole, never by index.
  \ of exactly the kind this project bans.
  LORA_BEG 2 LORA>B 255 LORA>B 255 LORA>B LORA_END
  LORA_BEG 131 LORA>B 15 LORA>B 0 LORA>B 0 LORA>B LORA_END
  \ ^ SetTx, timeout 0x0F0000 ticks
  500000
  BEGIN
    LORA_DIO1 LORA@ 0=
  WHILE
    1-
    DUP 0=
    IF DROP 0 EXIT THEN
  REPEAT
  DROP
  \ GetIrqStatus, then the TxDone bit (see LORA_IRQTX)
  LORA_BEG 18 LORA>B 0 LORA>B LORA_IRQTX LORA_END ;

: LORA_SLEEP ( -- ) 132 4 LORA_CMD1 ;
