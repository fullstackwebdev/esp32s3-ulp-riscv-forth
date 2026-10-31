\ os_hot.fs - P25 reorder. P24's definitions verbatim, order only.
\ Idle block: poll -> dispatch -> task switch -> sleep check.
\ os_tasks.fs - P24 group 1: tasks, round-robin queue, tick counter.
\ Compiled against P20 variant C's 40 primitives + boot_min.fs.
\ GUARDRAIL: this engine has no ALLOT, no VARIABLE and no DOES>; a variable is
\ CREATE + one cell and space is claimed by moving V_HERE  with !.
\ Using CREATE alone gives a DOVAR whose body is never reserved, so the next
\ header overwrites it - reserve the cell in the same line.
: VARIABLE  CREATE 0 , ;
: ALLOT     HERE + 4 ! ;
: CELLS     4 * ;

\ --- the 32-byte task record  ---
32 CONSTANT TASK-SZ
0  CONSTANT T>NEXT
4  CONSTANT T>DSP
8  CONSTANT T>RSP
12 CONSTANT T>IP
16 CONSTANT T>STATE
20 CONSTANT T>WAKE
24 CONSTANT T>WAIT
28 CONSTANT T>USER
\ task states  and the room limit
0 CONSTANT #FREE
1 CONSTANT #READY
2 CONSTANT #SLEEP
3 CONSTANT #BLOCK
4 CONSTANT #DEAD
4 CONSTANT #MAXTASK

CREATE TASK-POOL #MAXTASK TASK-SZ * ALLOT
VARIABLE RUNQ             \ head of the run queue
VARIABLE CUR              \ task holding CUR now
VARIABLE #TASKS
VARIABLE TICK             \ scheduler tick, the layer's only clock
VARIABLE TMP
VARIABLE DIAG             \ 0 = no error, else a named code
VARIABLE WM
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

: T-STATE!  T>STATE + ! ;

: NEXT-TASK 
  CUR @ 0= IF RUNQ @ ELSE
    CUR @ T>NEXT + @ DUP 0= IF DROP RUNQ @ THEN
  THEN ;

: TICK+  TICK @ 1+ TICK ! ;

\ WAKE-1   a sleeping task whose wake_at has been passed is ready.
: WAKE-1
  DUP T>STATE + @ #SLEEP = IF
    DUP T>WAKE + @ TICK @ SWAP < 0= IF
      #READY OVER T-STATE! 
    THEN
  THEN DROP ;

: WAKE-ALL  #MAXTASK 0 DO TASK-POOL I TASK-SZ * + WAKE-1 LOOP ;

\ YIELD: round robin. The record bookkeeping is Forth; the register half of the
\ switch  has no primitive in the 40-word set - see RESULT.md.
: YIELD
  NEXT-TASK DUP 0= IF DROP EXIT THEN
  CUR !
  TICK+
  WAKE-ALL ;

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

: PAUSE  YIELD ;                    \ give the queue a turn, stay ready

\ SLEEP-TICKS   sleep until the tick counter has advanced by n.
: SLEEP-TICKS
  TICK @ + CUR @ T>WAKE + !
  #SLEEP CUR @ T-STATE!  YIELD ;
