\ lora1.fs - SX1262 transmit driver in Forth, on the ULP-
\ RISC-V. The pins are set up HERE, by the coprocessor.
\ F-176 measured that a store to RTC_GPIO_OUT_W1TS from the
\ ULP does nothing until the ULP itself has set the SENS
\ clock gate, pad MUX_SEL, FUN_SEL = 0 and
\ RTC_GPIO_ENABLE_W1TS. That is why no bisect of program
\ content could flip the answer: the missing ingredient was
\ configuration, and it has to be written by the master that
\ drives the pad. NAMES ARE NOT COSMETICS. A header is 24
\ bits: imm(1) | xt(11) | hash(12), and no names are stored,
\ so a 12-bit djb2 hash IS a word's identity. `SET`, `CLR`,
\ `IN`, `SCK`, `MISO`, `BUSY` hash onto resident words and
\ the chip refuses them with `SCK?`, which for months looked
\ like "the coprocessor cannot drive the pads".
\ tools/hashcheck.py is a lint rule, so a colliding name
\ never reaches the board. Lines stay under 63 bytes (the
\ device input ring). BUDGET: this driver needs MEMSZ >=
\ 2550 of the pool. At 2540 the last two words (INIT, SEND)
\ fall off the end of the dictionary - the code area and the
\ header area meet in the middle, so the name that
\ disappears is whichever is furthest down, and NOTHING
\ reports it. `#k` and a `WORDS`-style probe will not show
\ it; only loading the file and asking for the last word
\ does.
\
\
8  CONSTANT NSSPAD
9  CONSTANT SCKPAD
10 CONSTANT MOSIPAD
12 CONSTANT NRSTPAD
13 CONSTANT BUSYPAD
\
\
: PIN! ( level pin -- )
  10 + 1 SWAP LSHIFT SWAP IF 41988 ELSE 41992 THEN ! ;
\ GUARDRAIL: the register must be READ. `42020 AND` (no
\ `@`) ANDs the bit
\ mask with the ADDRESS 0xA424, which is nonzero only for
\ the very bits the
\ address happens to set - so pad 11 always read 0, pad 9
\ always read 0, and
\ BUSYOK/RADIORESET "passed" on garbage while MISO was never
\ sampled at all.
\ Caught by asking both cores the same question with the
\ clock held high: HP
\ IN = 0x80400 and a bare `42020 @` = 0x80400 agreed, while
\ PIN@ said 0.
: PIN@ ( pin -- level )
  10 + 1 SWAP LSHIFT 42020 @ AND 0= 0= ;
\
\
\
: BITOUT ( b -- b*2 )
  DUP 128 AND IF 1 MOSIPAD PIN! ELSE 0 MOSIPAD PIN! THEN
  1 SCKPAD PIN! 0 SCKPAD PIN! 2 * ;
: >BYTE ( b -- )
  BITOUT BITOUT BITOUT BITOUT
  BITOUT BITOUT BITOUT BITOUT DROP ;
\ GUARDRAIL: the C HAL calls hal_wait_busy() BEFORE every
\ transfer, and this
\ is that wait, not a sleep. After a calibration the SX1262
\ holds RBUSY high
\ for milliseconds, and during that window it ignores the
\ SPI entirely: a
\ command issued there is lost with no answer and no error,
\ and GetStatus
\ reading 0x00 on a wired, awake chip is what that looks
\ like. The old word
\ slept 2 ms AFTER NSS had already dropped, which freed
\ nothing.
\ The loop is bounded (200 polls, ~200 ms worst case,
\ derived from MS being
\ one millisecond) so a radio that never frees the bus
\ cannot hang the
\ coprocessor. One line because BEGIN/UNTIL cannot straddle
\ a typed line
\ boundary: run_line zeroes the return stack per line.
: BUSY-LOW ( -- )
  200 BEGIN 1- 1 MS DUP 0= BUSYPAD PIN@ 0= OR UNTIL DROP ;
: NSSLO BUSY-LOW 0 NSSPAD PIN! ;
: NSSHI 1 NSSPAD PIN! ;
: BITREAD ( b -- b' )
  2 * 1 SCKPAD PIN! 11 PIN@ 0 SCKPAD PIN! IF 1 + THEN ;
: CLOCKLOW ( -- ) 0 MOSIPAD PIN! 1 SCKPAD PIN! 0 SCKPAD PIN! ;
\
\
\ GUARDRAIL: GetIrqStatus answers with TWO bytes, MSB first,
\ and TxDone is bit 0 of that 16-bit word. Clocking dummy
\ bytes and keeping the first bit read bit 15, which is
\ reserved and always 0 - that is why SEND answered 0.
: RD-BYTE ( -- b ) 0 BITREAD BITREAD BITREAD BITREAD
  BITREAD BITREAD BITREAD BITREAD ;
: RD2 ( -- w ) RD-BYTE 8 LSHIFT RD-BYTE OR ;
\
\ GUARDRAIL: this dictionary does NOT have DO/LOOP - those
\ live in the overlay, and a driver loaded at the plain
\ prompt has only the resident GUARDRAIL: this dictionary
\ does NOT have DO/LOOP, and a typed definition cannot hold
\ a loop across a line boundary: run_line zeroes the return
\ stack per line, so a `>R` left open at end of line is gone
\ before `R>` runs and the chip answers `stack?` while the
\ tokens of the next line get INTERPRETED (measured: WAIT-
\ DIO1 existed but INIT/SEND after it did not). A bounded
\ wait therefore lives in one line, or comes from the radio.
\
\ GUARDRAIL: DIO1 is a LEVEL, and the C driver waits on it
\ (docs/28 3.5). A fixed sleep can report TxDone for a
\ packet that never started - so the sleeping here is only
\ safe because SEND clears the IRQ with
\ ClearIrqStatus(0xFFFF) BEFORE SetTx, and because the
\ answer below is the chip's own GetIrqStatus word, not this
\ program's opinion of timing.
\
\ GUARDRAIL: the pads are already RTC-driven when INIT runs.
\ The main core configures them at boot (lora_pads_setup);
\ measured as ENABLE 0x005C0000 with no coprocessor code
\ having run (bits 18,19,20,22 of the +10 field are pads
\ 8,9,10,12), and a bare `1 MOSIPAD PIN!` then moves OUT to
\ 0x00540000. The coprocessor-side bring-up this file used
\ to carry cost about 200 B of dictionary for a
\ configuration the HP had already written, and it is the
\ dictionary that runs out, not the 7 932 B image.
\ RADIORESET returns whether BUSY cleared, and INIT refuses
\ to carry on
\ without it: a radio that does not come out of reset
\ answers every command
\ with a NAK, and the first symptom would be a TxDone that
\ never appears.
\
\ GUARDRAIL: a pad's INPUT BUFFER (RTC_IO_x_FUN_IE, bit 13
\ of the pad
\ register) has to be enabled or every read returns 0 - the
\ working C HAL
\ says this in a comment of its own, and the same trap cost
\ me months here:
\ "Reading back an OUTPUT pin without enabling the input
\ first returns 0 for
\ every pin". FUN_SEL (bits 16-17) must be 0 to put the pad
\ in RTC mode. The
\ three read-side pads are MISO 11, BUSY 13, DIO1 14, at
\ PADIO000 + 4*pad.
: INEN ( padreg -- )
  DUP @ 8192 OR 393216 INVERT AND SWAP ! ;

\ GUARDRAIL: this definition wraps across lines because
\ CMD_SIZE-1 = 63 B is the device input ring and an
\ over-long line is dropped SILENTLY. Folding
\ READPINS-ON/RADIORESET/BUSYOK into INIT once produced an 80 B
\ line: the board accepted the first lines and quietly lost the
\ reset check, so INIT returned 1 with an
\ un-reset radio. tools/lint_forth.py --repl (R21) is the gate;
\ tests/lora_two_board.py now calls it.
: INIT ( -- ok )
  42160 INEN 42168 INEN 42172 INEN
  1 NSSPAD PIN! 1 NRSTPAD PIN! 0 SCKPAD PIN!
  0 NRSTPAD PIN! 2 MS 1 NRSTPAD PIN! 5 MS
  1 MS BUSYPAD PIN@ 0= 0= IF 0 EXIT THEN
  NSSLO 128 >BYTE 0 >BYTE NSSHI
  NSSLO 150 >BYTE 1 >BYTE NSSHI
  NSSLO 151 >BYTE 2 >BYTE 0 >BYTE 1 >BYTE 64 >BYTE NSSHI
  NSSLO 137 >BYTE 127 >BYTE NSSHI
  NSSLO 157 >BYTE 1 >BYTE NSSHI
  NSSLO 138 >BYTE 1 >BYTE NSSHI
  NSSLO 134 >BYTE 54 >BYTE 65 >BYTE 153 >BYTE 153 >BYTE NSSHI
  NSSLO 152 >BYTE 215 >BYTE 219 >BYTE NSSHI
  NSSLO 149 >BYTE 2 >BYTE 2 >BYTE 0 >BYTE 1 >BYTE NSSHI
  NSSLO 142 >BYTE 14 >BYTE 4 >BYTE NSSHI
  NSSLO 143 >BYTE 0 >BYTE 0 >BYTE NSSHI
  NSSLO 139 >BYTE 9 >BYTE 4 >BYTE 1 >BYTE 0 >BYTE NSSHI
  NSSLO 140 >BYTE 0 >BYTE 8 >BYTE 0 >BYTE 4 >BYTE
  1 >BYTE 0 >BYTE NSSHI
  NSSLO 8 >BYTE 255 >BYTE 255 >BYTE 0 >BYTE 0 >BYTE
  0 >BYTE 0 >BYTE 0 >BYTE 0 >BYTE NSSHI
  1 ;
\
\ Clear the IRQ before SetTx (DIO1 is a level), wait past
\ the air time, then read TxDone out of the chip's own IRQ
\ status.
: SEND ( -- ok )
  NSSLO 14 >BYTE 0 >BYTE
  165 >BYTE 49 >BYTE 50 >BYTE 51 >BYTE NSSHI
  NSSLO 2 >BYTE 255 >BYTE 255 >BYTE NSSHI
  NSSLO 131 >BYTE 15 >BYTE 0 >BYTE 0 >BYTE NSSHI
  200 MS
  NSSLO 18 >BYTE 0 >BYTE RD2 NSSHI 1 AND ;
