\ os_events.fs - P24 group 2: the event ring, ON-GPIO, EMIT-EVENT,
\ POLL-EVENTS. Ring of 8 records, 12 B each .
8 CONSTANT #EVQ
12 CONSTANT EV-SZ
1 CONSTANT #EV-KEY
2 CONSTANT #EV-GPIO
4 CONSTANT #EV-TICK
CREATE EV-RING #EVQ EV-SZ * ALLOT
VARIABLE EV-H            \ head: next slot to write
VARIABLE EV-T            \ tail: next slot to dispatch
VARIABLE EV-N            \ entries in the ring
VARIABLE EA              \ scratch: the slot address under construction
VARIABLE EN              \ scratch: POLL-EVENTS dispatch count
VARIABLE KIN             \ key pending, set by the key event, read by KEY?
VARIABLE GPIOMASK
VARIABLE GPIOXT

: EV!   EV-SZ * EV-RING + ;

\ EMIT-EVENT   append; a full ring is a named error, not a clamp.
: EMIT-EVENT
  EV-N @ #EVQ = IF DROP DROP 2 DIAG ! EXIT THEN
  SWAP                       \ GUARDRAIL: ! is , so with the
  EV-H @ EV! DUP EA !        \ slot address on top the ARG would land in the
  EA @ !                     \ kind cell - swap kind up before ! and stage the
  EA @ 4 + !                 \ address in EA; otherwise the ring self-corrupts.
  EV-H @ 1+ #EVQ MOD EV-H !
  EV-N @ 1+ EV-N ! ;

\ WAKE-MASK   release every blocked task whose wait mask intersects m.
: WAKE-MASK
  WM !
  #MAXTASK 0 DO
    TASK-POOL I TASK-SZ * +
    DUP T>STATE + @ #BLOCK = IF
      DUP T>WAIT + @ WM @ AND IF
        #READY OVER T-STATE! 
      THEN
    THEN DROP
  LOOP ;

\ ON-GPIO   register the gpio event handler.
: ON-GPIO  GPIOXT ! GPIOMASK ! ;

: EV-GPIO-DO  GPIOMASK @ IF GPIOXT @ EXECUTE THEN ;

\ POLL-EVENTS   dispatch one pass of the ring, return how many.
: POLL-EVENTS
  0 EN !
  BEGIN EV-N @ WHILE
    EV-T @ EV! EA !
    EA @ @ DUP #EV-TICK =
    IF DROP TICK+
    ELSE DUP #EV-GPIO =
      IF DROP #EV-GPIO WAKE-MASK EV-GPIO-DO
      ELSE DUP #EV-KEY =
        IF DROP -1 KIN !
        ELSE DROP 3 DIAG !
        THEN
      THEN
    THEN
    EV-T @ 1+ #EVQ MOD EV-T !
    EV-N @ 1- EV-N !
    EN @ 1+ EN !
  REPEAT
  EN @ ;
