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
