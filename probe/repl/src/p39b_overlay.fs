\ p39b_overlay.fs — the resident/overlay split. Baked into the image and into the block-flag host binary.
\
\ GUARDRAIL: the overlay words live in their OWN baked file, not in p39_prelude.fs, because the plain host
\ suite compiles the engine WITHOUT the block layer (tests/run.sh host_suite has no -DP33_BLOCK/-DOVL_LOAD)
\ and would fail on `LOAD?` the moment this text was in the shared prelude.
\
\ GUARDRAIL: HERE and LATEST are GETTERS - they push the VALUE of the sys-var (the code pointer and the
\ newest header address), not the address of a variable holding it. `SEAL`'s first version wrote
\ `HERE bh ! ... LATEST bl !`, which was fine, and then `OVL` wrote `bh @ HERE !`, which stores INTO mem[]
\ at address = the code pointer's value: measured, it clobbered the header of the last resident word with
\ the number 781 (0x30D = 781 written at 781) and the overlay's word then resolved, while every earlier
\ resident word became unfindable. To WRITE the pointers you need the sys-var addresses themselves.
\ GUARDRAIL: SEAL and OVL write to DIFFERENT KINDS of address and mixing them fails silently: SEAL stores
\ INTO the cells bh/bl (so it needs bh, which pushes a cell address), OVL stores INTO the sys-vars (so it
\ needs VH/VL, which are the sys-var addresses). Writing `HERE VH !` in SEAL, as the second version did,
\ stores into a sys-var that was just read - a no-op - and leaves bh/bl at 0, so the next OVL rewinds the
\ dictionary to address 0 and every word becomes unfindable (measured: `0:?` on the first overlay line).
\ GUARDRAIL: VH and VL are the only re-typed numbers in this file, and they are re-typed on purpose: there
\ is no word that returns the address of a sys-var, and adding one costs a primitive (~20 B of .text).
\ They are guarded by tests/overlay.fs, which fails loudly if they move: SEAL then OVL twice must return to
\ the SAME free space and a sealed word must still be findable afterwards. If a sys-var is added below
\ V_HERE/V_LATEST in uforth.c's enum, that test breaks instead of the dictionary rotting.
4 CONSTANT VH              \ address of V_HERE in uforth.c's sys-var enum
8 CONSTANT VL              \ address of V_LATEST
12 CONSTANT VS             \ address of V_SEAL: set by SEAL, read by mkentry to refuse name collisions
CREATE bh 0 ,              \ sealed V_HERE
CREATE bl 0 ,              \ sealed V_LATEST
CREATE ovlrun 0 ,          \ hook slot: the current overlay's entry point
\ GUARDRAIL: SEAL publishes V_LATEST into V_SEAL as well. That single store is what turns the silent
\ shadowing hazard into a loud ERR_DICT at definition time: from then on, every definition is checked
\ against the resident headers (see mkentry). It must be the SEALED latest, i.e. bl, not the current one.
: SEAL  ( -- )  HERE bh !  LATEST bl !  LATEST VS ! ;
: OVL   ( blk -- )  bh @ VH !  bl @ VL !  LOAD ;
: GO    ( -- )  ovlrun @ EXECUTE ;

\ GUARDRAIL: PHASE is the call-site transparency layer, and it is deliberately one word: it remembers which
\ block is loaded, so a resident driver can say `3 PHASE` without knowing whether the phase is already in
\ memory. It must be called from RESIDENT code (below the seal) - a phase that calls PHASE overwrites its own
\ body while it is executing. That rule has no runtime guard (a guard would need the call depth, which the
\ engine keeps but does not expose).
\ GUARDRAIL: the cell is CURBLK, not PHASE. word() upcases every token, so `phase` and `PHASE` are the
\ same name: the colon definition silently replaced the variable, and `phase .` then ran the word with an
\ empty stack (ERR_STACK). Any cell whose name is a prefix-alike of a word must be named apart.
CREATE curblk -1 ,         \ which block is loaded, -1 = none
: PHASE ( blk -- )  DUP curblk @ = IF DROP EXIT THEN  DUP curblk !  0 ovlrun !  OVL ;
\ GUARDRAIL: PHASE CLEARS the hook cell. With the source switch, LOAD arms the block and returns, so the
\ block's text runs when the interpreter next asks for a token - i.e. AFTER the rest of the current line.
\ A `PHASE GO` on one line would therefore GO with the hook the PREVIOUS phase left behind, which is the
\ stale-hook garbage class. Clearing it makes that case execute token 0, and EXECUTE of 0 is a named error
\ (it used to dispatch into mem[0..1] and run garbage from address 2). A phase block must set the hook in
\ its own text, before the line that GOes.
\ GUARDRAIL: the first version was `... IF DROP ELSE DUP phase ! OVL THEN ;` and it underflowed on the
\ load path: `DUP <cell> !` consumes the block number, so OVL was called with an empty stack (ERR_STACK).
\ The `EXIT` form keeps one copy for OVL; the alternative is a cell to re-push, i.e. more state.
