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
48 CONSTANT #STK          \ 32 data + 16 return cells, 192 B per task

CREATE TASK-POOL #MAXTASK TASK-SZ * ALLOT
VARIABLE RUNQ             \ head of the run queue
VARIABLE CUR              \ task holding CUR now
VARIABLE #TASKS
VARIABLE TICK             \ scheduler tick, the layer's only clock
VARIABLE TMP
VARIABLE DIAG             \ 0 = no error, else a named code
VARIABLE WM

: T-STATE!  T>STATE + ! ;
\ GUARDRAIL: 0 is a valid task address sentinel only because the pool starts
\ above the headers; scanning with "TMP @ 0="  rather than a flag on
\ the stack is what survives the missing UNLOOP - EXIT inside DO..LOOP leaves
\ the return stack dirty, so no loop body below exits early.
: NEXT-FREE 
  0 TMP !
  #MAXTASK 0 DO
    TMP @ 0= IF
      TASK-POOL I TASK-SZ * +
      DUP T>STATE + @ 0= IF TMP ! ELSE DROP THEN
    THEN
  LOOP
  TMP @ ;

\ TASK   allocate a record + a 192 B stack, queue it, return record.
: TASK
  NEXT-FREE DUP 0= IF DROP 1 DIAG ! 0 EXIT THEN
  TMP !
  TMP @ T>USER + !                  \ user cell = the body xt
  #READY TMP @ T-STATE! 
  HERE #STK CELLS ALLOT             \ per-task stack, base left on the stack
  DUP TMP @ T>RSP + !
  32 CELLS + TMP @ T>DSP + !
  RUNQ @ TMP @ T>NEXT + !           \ push onto the run-queue head
  TMP @ RUNQ !
  #TASKS @ 1+ #TASKS !
  TMP @ ;

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

: PAUSE  YIELD ;                    \ give the queue a turn, stay ready

\ SLEEP-TICKS   sleep until the tick counter has advanced by n.
: SLEEP-TICKS
  TICK @ + CUR @ T>WAKE + !
  #SLEEP CUR @ T-STATE!  YIELD ;

\ STOP   block on an event mask until WAKE-MASK releases it.
: STOP
  CUR @ T>WAIT + !
  #BLOCK CUR @ T-STATE!  YIELD ;

\ TASKS   print "count state state state state", digits only: the layer's
\ number printer lives in the introspection group and is compiled later.
: TASKS
  #TASKS @ 48 + EMIT 32 EMIT
  #MAXTASK 0 DO
    TASK-POOL I TASK-SZ * + T>STATE + @ 48 + EMIT 32 EMIT
  LOOP ;
