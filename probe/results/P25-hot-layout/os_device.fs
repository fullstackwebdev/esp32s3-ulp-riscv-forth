\ os_device.fs - P24 group 5: device words. GPIO@ GPIO! ADC@ are primitives;
\ this group adds the timing word and the two pin conveniences the REPL uses.
\ MS   the trimmed set dropped MS  and WAKE , so the
\ layer's clock is its own tick counter: MS advances the tick and yields, one
\ tick per millisecond. It is a scheduler-driven delay, not a hardware timer.
: MS  0 DO TICK+ YIELD LOOP ;
: PIN?    GPIO@ 0= 0= ;            \ read a pin as a flag
: PIN!    GPIO! ;
\ PIN-WAIT   spin on a pin until it reads want.
: PIN-WAIT  SWAP BEGIN OVER GPIO@ = UNTIL DROP DROP ;
