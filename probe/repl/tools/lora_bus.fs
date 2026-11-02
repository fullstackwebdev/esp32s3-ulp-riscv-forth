\ lora_bus.fs - one witness word for tests/lora_bus.py.
\
\ Deliberately ONE word. The first version of this file defined eight, and they did not fit the dictionary
\ next to the driver (ERR_DICT), which I nearly read as a bus failure. A single short definition fits in the
\ gap that is left, which is what makes it usable as an instrument rather than a second driver.
\
\ WHAT IT PROVES: it returns the MOST SIGNIFICANT bit of the byte the SX1262 has in its own RAM at offset 0.
\ The test writes 0x80 and expects 1, then 0x00 and expects 0. Both directions are required: a floating or
\ stuck input reads 0 in both cases, so only the 1-answer half distinguishes a live MOSI from a dead one,
\ and only the 0-answer half distinguishes a live MISO from a wire held high (R18).
\
\ PROTOCOL, taken from the working C driver rather than invented (docs/29, sx126x_min.c):
\   ReadBuffer is opcode 0x1E, then the offset byte, then ONE dummy byte, and the data byte follows.
\ The first version of this file sent opcode and offset only, so the answer was always 0 and the failure
\ looked like "the coprocessor cannot drive the bus" when it was a missing clock. ReadBuffer also wants
\ BUSY low first (hal_wait_busy in the C driver); the driver's WB does that.
\
\ GUARDRAIL: R21 counts the newline, so a line may hold 62 bytes. Long lines are truncated silently.

: RAMREADBIT WB IF [ 30 >B 0 >B 0 >B <C ] ELSE 99 THEN ;
