\ os_cold.fs - P25 reorder. P24's definitions verbatim, order only.
\ Idle block: poll -> dispatch -> task switch -> sleep check.
48 CONSTANT #STK          \ 32 data + 16 return cells, 192 B per task
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

\ EMIT-EVENT   append; a full ring is a named error, not a clamp.
: EMIT-EVENT
  EV-N @ #EVQ = IF DROP DROP 2 DIAG ! EXIT THEN
  SWAP                       \ GUARDRAIL: ! is , so with the
  EV-H @ EV! DUP EA !        \ slot address on top the ARG would land in the
  EA @ !                     \ kind cell - swap kind up before ! and stage the
  EA @ 4 + !                 \ address in EA; otherwise the ring self-corrupts.
  EV-H @ 1+ #EVQ MOD EV-H !
  EV-N @ 1+ EV-N ! ;
\ os_repl.fs - P24 group 3: the REPL task, prompt, error reporting, KEY?.
\ TYPE is a primitive and is NOT redefined here.
: CR      10 EMIT ;
: SPACE   32 EMIT ;
: PROMPT  62 EMIT SPACE ;
: .CODE   48 + EMIT ;               \ one-digit diagnostic code
: .ERR    63 EMIT DIAG @ .CODE SPACE 0 DIAG ! ;
: OK?     DIAG @ 0= IF 46 EMIT SPACE ELSE .ERR THEN ;
\ KEY?   non-blocking: the trimmed set dropped the KEY? primitive, so
\ the layer owns the pending flag and the KEY event sets it .
: KEY?    KIN @ ;
: ECHO    DUP EMIT ;
\ QUIT is the REPL task body: prompt, dispatch events, take one key, yield.
\ Line interpretation itself is the engine's interpret; there is no EVALUATE
\ in the 40-primitive set, so QUIT does not re-enter the outer interpreter.
: QUIT
  BEGIN
    PROMPT
    POLL-EVENTS DROP
    KEY? IF KEY ECHO THEN
    0 KIN !
    OK?
    YIELD
  AGAIN ;
\ os_introspect.fs - P24 group 4: WORDS, .S, ?, and the number printer.
\ GUARDRAIL: W@ was trimmed from the 40, so the 2-byte header link has to be
\ rebuilt from two C@ - a one-byte link read silently walks into the name.
: LINK@   DUP C@ SWAP 1+ C@ 256 * OR ;
: .NAME      DUP 3 + SWAP 2 + C@ 31 AND TYPE ;
: .DIGIT     48 + EMIT ;
: U.                               \ unsigned decimal, recursive
  DUP 9 > IF DUP 10 / U. 10 MOD .DIGIT ELSE .DIGIT THEN ;
: .    DUP 0< IF 45 EMIT NEGATE THEN U. ;
: ?    @ . ;
: WORDS
  LATEST @ BEGIN DUP WHILE DUP .NAME SPACE DUP LINK@ REPEAT DROP ;
\ .S   DEPTH is not in the 40-primitive set, so the layer cannot print
\ the stack depth; .S prints the top cell non-destructively and says so here.
: .S  DUP . SPACE ;
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
