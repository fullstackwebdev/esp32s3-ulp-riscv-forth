\ lora_rx.fs - SX1262 RECEIVE in Forth, on the ULP, reusing
\ lora1.fs's SPI words.
\
\ Load lora1.fs FIRST: it defines PIN!, >BYTE, RD-BYTE, RD2,
\ NSSLO, NSSHI, INEN, INIT, SEND. This file adds only the
\ receive path, so the measured transmit path stays
\ byte-identical and both boards can work in both directions.
\
\ MEASURED VOCABULARY on this kernel: 0= 1- 1+ < = AND OR XOR
\ LSHIFT RSHIFT EMIT DUP DROP SWAP OVER . /MOD @ ! KEY.
\ MISSING: > 0> 0< MOD ABS MIN MAX, and NO DO/LOOP (it lives in
\ the overlay). Byte loops are BEGIN/WHILE/REPEAT with
\ the count riding on the stack.
\
\ OPCODES (docs/28 appendix): 0x82 SetRx, 0x02 ClearIrqStatus,
\ 0x12 GetIrqStatus, 0x13 GetRxBufferStatus,
\ 0x1E ReadBuffer, 0x8C SetPacketParams. IRQ bits: 0x0002
\ RxDone, 0x0040 CrcErr, 0x0200 Timeout.
\
\ GUARDRAIL: EVERY LINE HERE STAYS UNDER 63 BYTES. The device
\ input ring holds CMD_SIZE-1 = 63 and refuses the rest
\ SILENTLY - the definition simply never exists, and the
\ failure then shows up as `NAME?` when something calls it.
\ Measured the hard way\ GUARDRAIL: names are SHORT because a
\ definition must fit one typed line under 63 B, not because
\ they are
\ precious: the dictionary stores no name bytes, only
\ `imm(1)|xt(11)|hash(12)`, so `SR` costs exactly what `SETRX`
\ costs. Long names are what pushed the receive words over the
\ input ring, and a line over 63 B is dropped with no
\ message at all.
\ GUARDRAIL: every definition is ONE line, with any
\ IF..ELSE..THEN complete on that line. A definition split
\ across
\ lines loses the compiler's control state: measured, RXTAKE
\ written across two lines answered `RXLEN?` then
\ `ERR_STACK` and the word never existed, while every word in
\ its body did.
\ IRQ bits: 0x0002 RxDone, 0x0040 CrcErr, 0x0200 Timeout. Ops:
\ 0x82 SetRx, 0x02 ClearIrq, 0x12 GetIrqStatus,
\ 0x13 GetRxBufferStatus, 0x1E ReadBuffer, 0x8C
\ SetPacketParams.
: SR NSSLO 130 >BYTE 255 >BYTE 255 >BYTE 255 >BYTE NSSHI ;
: RC NSSLO 2 >BYTE 255 >BYTE 255 >BYTE NSSHI ;
: IQ NSSLO 18 >BYTE 0 >BYTE RD2 NSSHI ;
\ Packet params are NOT re-sent here: INIT sets explicit header
\ + length 4 + CRC, which is what both
\ ends of this test send. Setting a larger maximum cost 34 B in
\ a dictionary that had none to give.
: RL NSSLO 19 >BYTE RD-BYTE DROP RD-BYTE RD-BYTE NSSHI ;
: RDUMP BEGIN DUP WHILE RD-BYTE . 32 EMIT 1- REPEAT DROP ;
: RB NSSLO 30 >BYTE >BYTE RD-BYTE DROP RDUMP NSSHI ;
: RXTAKE DUP 2 AND IF DROP RL RB RC 1 ELSE DROP RC 0 THEN ;
: RX1 RC SR 250 MS IQ ;
