\ seg.fs — P36: code overlays. Resident. No C: this file is the whole loader and directory.
\
\ Code is data: a colon definition is a token list, so an app can be compiled into one fixed 512 B
\ window, written to a block, dropped, and fetched back. The window is the far buffer P34 already
\ pays for (FAR-XFER hands its Forth address over, so this file spells no address at all) — the
\ address is fixed because it is MEMSZ, and that fixedness is what makes saved tokens valid.
\
\ GUARDRAIL: compile into the window by moving HERE, never by writing a second compiler — a
\ placement rule anywhere else would let a token be emitted at an address the loader later moves,
\ which is exactly the relocating-loader cost this probe is trying to avoid (P33's hard-coded 908
\ is the same class of bug: an address written down instead of fetched).
\ GUARDRAIL: every slot of the window is read back through P() (rb/wr8 in uforth.c), so a window at
\ an address >= MEMSZ only works because the P34 far decode covers it. A window carved out of mem[]
\ would have to move the dictionary instead.
\ GUARDRAIL: this file must be loaded AFTER paging.fs, because it uses FAR-XFER/FAR-READ and the
\ shadowed C! that the poison loop relies on. Loading it before gives `FAR-XFER?` at boot.

4 CONSTANT SEGMAX                       \ directory depth: 4 apps. Each line is 3 cells (12 B).

CREATE SBASE 0 ,                        \ the window's Forth address (fixed; == MEMSZ under P34_FAR)
CREATE SHERE 0 ,                        \ resident HERE saved at SEG-BEGIN, restored at SEG-SAVE
CREATE SLATEST 0 ,                      \ resident LATEST saved at SEG-BEGIN, restored at SEG-SAVE
CREATE SCUR 0 ,                         \ id of the segment whose bytes are in the window; 0 = none
CREATE SXT  0 , 0 , 0 , 0 ,             \ directory: entry xt per segment (0 = no segment)
CREATE SBLK 0 , 0 , 0 , 0 ,             \ directory: the block it was saved to
CREATE SLENX 0 , 0 , 0 , 0 ,            \ directory: bytes emitted (HERE - SBASE at SEG-SAVE)

: SEGXT  ( n -- a ) 4 * SXT + ;
: SEGBLK ( n -- a ) 4 * SBLK + ;
: SREC   ( n -- a ) 4 * SLENX + ;

\ system variables, by their offsets in mem[] — the engine keeps HERE at 4, LATEST at 8 (uforth.c).
: HERE@   ( -- a ) 4 RAW@ ;
: HERE!   ( a -- ) 4 RAW! ;
: LATEST@ ( -- h ) 8 RAW@ ;
: LATEST! ( h -- ) 8 RAW! ;

: SEG-INIT ( -- )
  \ GUARDRAIL: take the window address from FAR-XFER (op 2 = abort, no server contact), never from a
  \ literal: the value has to be whatever P() decodes as the far buffer, and the primitive is the
  \ only thing that knows it (P34's reason for pushing it).
  2 0 FAR-XFER DROP SBASE ! ;

\ GUARDRAIL: DO/LOOP are primitives spelled (DO)/(LOOP) and control.fs does not name them, so the
\ poison loop is spelled with BEGIN/WHILE/REPEAT — a DO here is `DO?` at load time, not a loop.
: SEG-FILL ( -- ) 0 BEGIN DUP 512 < WHILE 63 OVER SBASE @ + C! 1+ REPEAT DROP ;

: SEG-BEGIN ( n -- )
  DUP 0 < IF DROP ." ERR_SEG_UNKNOWN " EXIT THEN
  DUP SEGMAX < 0= IF DROP ." ERR_SEG_UNKNOWN " EXIT THEN
  DUP SCUR !
  HERE@ SHERE ! LATEST@ SLATEST !
  \ GUARDRAIL: poison the whole window before compiling into it. A stale token that survives into
  \ another segment must land on something that is not a token stream, or the corruption is silent
  \ (the dangerous case this probe hunts).
  SEG-FILL
  SBASE @ HERE! SLATEST @ LATEST!
  DUP SEGXT 0 SWAP !
  DUP SEGBLK 0 SWAP !
  DUP SREC 0 SWAP !
  DROP ." SEG-BEGIN " SCUR @ . SP ;

: SEG-ENTRY ( xt -- ) SCUR @ SEGXT ! ;

: SEG-SAVE ( blk -- )
  DUP 7 < 0= IF DROP ." ERR_SEG_UNKNOWN " EXIT THEN
  DUP SCUR @ SEGBLK !                    \ directory: where the bytes go
  HERE@ SBASE @ - SCUR @ SREC !          \ directory: how many bytes the segment emitted
  FBLK !                                 \ FAR-SAVE sends the block FBLK names
  \ GUARDRAIL: SEG-SAVE must restore HERE to the *resident* top, not to the window start. With HERE
  \ left at SBASE, the first ordinary `: ... ;` after a save is compiled over the live overlay, and
  \ the operator sees a normal "ok" while the app he just ran is gone.
  SHERE @ HERE! SLATEST @ LATEST!
  FAR-SAVE IF ." ERR_SAVE " ." FAILED " EXIT THEN
  ." SEG-SAVE " SCUR @ . ." blk " SCUR @ SEGBLK @ . ." len " SCUR @ SREC @ . SP ;

: SEG-LOAD ( n -- )
  DUP 0 < IF DROP ." ERR_SEG_UNKNOWN " EXIT THEN
  DUP SEGMAX < 0= IF DROP ." ERR_SEG_UNKNOWN " EXIT THEN
  DUP SEGBLK @ 0= IF DROP ." ERR_SEG_NONE " EXIT THEN
  DUP SEGBLK @ FAR-READ                  \ ( n st ) — fetches the segment back into the window
  IF SWAP DROP FAR-FAIL EXIT THEN
  SCUR ! ." SEG-LOAD " SCUR @ . SP ;

: SEG-CLEAR ( -- )
  \ GUARDRAIL: evict the block cache (FBLK = -1) as part of clearing. FAR-READ short-circuits when
  \ the block number is already resident, so a "clear then load" cycle would hand back the modified
  \ window and call it a reload — the proof would pass without a transfer ever happening.
  SEG-FILL -1 FBLK ! 0 SCUR ! ." SEG-CLEAR " ;

: SEG-WORD ( n -- xt )
  DUP 0 < IF DROP ." ERR_SEG_UNKNOWN " 0 EXIT THEN
  DUP SEGMAX < 0= IF DROP ." ERR_SEG_UNKNOWN " 0 EXIT THEN
  DUP SEGXT @ 0= IF DROP ." ERR_SEG_NONE " 0 EXIT THEN
  \ GUARDRAIL: the segment number is still under the xt here — `SEGXT @ ;` leaks one cell per call and
  \ the 16-cell stack is full after 16 lookups, reported as a stack overflow lines later.
  SEGXT @ SWAP DROP ;

\ Two call paths, and they are different words because the engine cannot check the second one:
\   APP ( n -- )       resident -> overlay. Refused with ERR_SEG_STALE if segment n's bytes are not
\                      in the window any more, with ERR_SEG_NONE if it was never saved.
\   SEG-CALL ( n -- )  overlay -> overlay. ALWAYS refused: the window holds the caller, so the target
\                      cannot be resident, and there is no state in which it could be. This is not a
\                      runtime check that might miss; it is the design (see RESULT.md, dangerous case).
\ GUARDRAIL: APP has no epilogue, and must not be given one. EXECUTEing a body whose EXIT sees ip==0
\ leaves vm_enter and returns to the C interpreter, so *no token after EXECUTE in this word runs*
\ (measured: `1 SRUN ! EXECUTE 0 SRUN !` left SRUN set for ever, so every later call was refused).
\ A flag cleared after the call is therefore impossible in Forth here; that is exactly why the
\ overlay-to-overlay refusal is a separate word whose whole body is the refusal.
: APP ( n -- )
  DUP 0 < IF DROP ." ERR_SEG_UNKNOWN " EXIT THEN
  DUP SEGMAX < 0= IF DROP ." ERR_SEG_UNKNOWN " EXIT THEN
  DUP SEGXT @ 0= IF DROP ." ERR_SEG_NONE " EXIT THEN
  DUP SCUR @ = IF
    \ GUARDRAIL: `SEGXT @` alone leaves the segment number under the xt and EXECUTE would run it —
    \ drop it before the call, or APP leaks a cell per call into a 16-cell stack.
    SEGXT @ SWAP DROP                  \ ( xt ) — resolve last, so nothing stale is ever EXECUTEd
    EXECUTE EXIT THEN
  ." ERR_SEG_STALE " DROP ;

: SEG-CALL ( n -- ) ." ERR_SEG_UNRESIDENT " DROP ;
