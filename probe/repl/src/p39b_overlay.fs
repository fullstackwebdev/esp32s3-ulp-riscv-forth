\ p39b_overlay.fs — the resident overlay manager and event loop. Baked into the image and into the block-flag
\ host binary. Free space it costs is measured by tests/capacity.sh (row 1 of the A/B); it must be reported, not
\ hidden, because it is a regression against the single-image build.
\
\ GUARDRAIL: the overlay words live in their OWN baked file, not in p39_prelude.fs, because the plain host suite
\ compiles the engine WITHOUT the block layer (tests/run.sh host_suite has no -DP33_BLOCK/-DOVL_LOAD) and fails on
\ `LOAD?` the moment this text is in the shared prelude.
\
\ GUARDRAIL: SEAL and OVL write to DIFFERENT KINDS of address. HERE/LATEST are getters, so SEAL stores INTO its own
\ cells (bh, bl) while OVL stores INTO the sys-vars (VH, VL). Writing `HERE VH !` in SEAL is a no-op that leaves
\ bh at 0, and the next OVL then rewinds the dictionary to address 0 - every word becomes unfindable (measured).
\
\ GUARDRAIL: VH/VL/VS are the only re-typed numbers here, and they are guarded by tests/overlay.fs and
\ tests/overlay_collide.fs, which fail loudly if they move. There is no word that returns the address of a sys-var;
\ adding one costs a primitive.
4 CONSTANT VH              \ address of V_HERE in uforth.c's sys-var enum
8 CONSTANT VL              \ address of V_LATEST
12 CONSTANT VS             \ address of V_SEAL: set by SEAL, read by mkentry to refuse name collisions
CREATE bh 0 ,              \ sealed V_HERE
CREATE bl 0 ,              \ sealed V_LATEST
CREATE ovlrun 0 ,          \ hook: the loaded phase's handler
\ GUARDRAIL: the cell is CURBLK, not PHASE. word() upcases every token, so `phase` and `PHASE` are the same name:
\ the colon definition silently replaced the variable and every use underflowed. Name cells apart from words.
CREATE curblk -1 ,         \ which block is loaded, -1 = none
CREATE q 0 C, 0 C, 0 C, 0 C,   \ 4-byte event ring: ALLOT does not exist, C, is how bytes are reserved
CREATE qh 0 , CREATE qt 0 , CREATE qovf 0 , CREATE brt 0 ,

: SEAL  ( -- )  HERE bh !  LATEST bl !  LATEST VS ! ;
: OVL   ( blk -- )  bh @ VH !  bl @ VL !  LOAD ;
: GO    ( -- )  ovlrun @ EXECUTE ;
\ GUARDRAIL: brt counts BLOCK ROUND TRIPS (row 5 of the A/B) and is incremented only on a REAL switch, below the
\ equality test, so a same-phase event provably causes zero block traffic. Do not hoist the increment.
\ GUARDRAIL: PHASE clears the hook. With the source switch, LOAD arms the block and returns, so the block's text
\ runs when the interpreter next asks for a token - i.e. after the rest of the current line. A `PHASE GO` on one
\ line would therefore GO with the previous phase's hook, the stale-hook class; clearing it makes that case
\ execute token 0, which is a named error.
: PHASE ( blk -- )  DUP curblk @ = IF DROP EXIT THEN  DUP curblk !  0 ovlrun !  brt @ 1 + brt !  OVL ;

\ ---- event loop ----------------------------------------------------------------------------------------------
\ GUARDRAIL: POST REJECTS on a full ring and counts the loss in qovf. This engine has no Forth-level message
\ primitive (msg() is C-only), so the rejection is made countable rather than named - and it never overwrites the
\ oldest event, which would be a silent loss.
\ GUARDRAIL: PUMP RETURNS when the queue is empty instead of spinning: there is no idle/sleep primitive, so a
\ spinning loop would burn the ULP's only execution context and starve the console, and returning is what makes
\ the behaviour testable. Same-phase events still cost zero block traffic.
\ GUARDRAIL: handlers are ( ev -- ) and must never call PHASE or PUMP - a handler that switches phase would ask
\ the engine to erase the code it is running. The loop arms the switch and leaves via EXIT; the interpreter then
\ loads the block, whose own text re-enters PUMP.
\ GUARDRAIL: `BEGIN 1 WHILE ... REPEAT`, never a bare BEGIN/REPEAT: REPEAT resolves the branch a WHILE emitted and
\ underflows the compiler's stack without one (measured). AGAIN does not exist in this engine.
: POST ( ev -- ) qt @ 1 + 3 AND qh @ = IF DROP 1 qovf ! EXIT THEN q qt @ + C! qt @ 1 + 3 AND qt ! ;
: EV?  ( -- f )  qh @ qt @ <> ;
: EV@  ( -- ev )  q qh @ + C@ qh @ 1 + 3 AND qh ! ;
: RESET ( -- )  -1 curblk ! 0 ovlrun ! 0 qh ! 0 qt ! 0 qovf ! ;
: PUMP ( -- )
  BEGIN 1 WHILE
    EV? 0= IF EXIT THEN
    q qh @ + C@ 8 +  DUP curblk @ = IF  DROP EV@ ovlrun @ EXECUTE
    ELSE  DUP curblk ! PHASE EXIT THEN
  REPEAT ;
