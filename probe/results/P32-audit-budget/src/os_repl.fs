\ os_repl.fs - P26 group 3: the QUIT task, the prompt, the error report.
CREATE KIN 0 ,             \ a key is pending
\ GUARDRAIL: KEY is blocking and the 40-word set dropped KEY?; the only
\ way to take a line without blocking is to check the layer's own pending
\ flag before calling KEY at all.
: GOTKEY  -1 KIN ! ;       \ hook target: platform posts (' GOTKEY)

\ ?ERR report the diagnostic. One digit: every code in this layer is 1.
\ One digit, and it clears DIAG so the prompt is not drowned by a repeat.
: ?ERR    63 EMIT DIAG @ 48 + EMIT 0 DIAG ! ;

\ QUIT prompt, dispatch the ring, take one key if one is pending, yield.
\ It never calls a blocking primitive unless the layer already knows the
\ data is there, so it always retires.
: QUIT
  BEGIN
    62 EMIT
    POLL-EVENTS
    KIN @ IF KEY EMIT 0 KIN ! THEN
    DIAG @ IF ?ERR THEN
    YIELD
  AGAIN ;
