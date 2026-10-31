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
CREATE bh 0 ,              \ sealed V_HERE
CREATE bl 0 ,              \ sealed V_LATEST
CREATE ovlrun 0 ,          \ hook slot: the current overlay's entry point
: SEAL  ( -- )  HERE bh !  LATEST bl ! ;
: OVL   ( blk -- )  bh @ VH !  bl @ VL !  LOAD ;
: GO    ( -- )  ovlrun @ EXECUTE ;
