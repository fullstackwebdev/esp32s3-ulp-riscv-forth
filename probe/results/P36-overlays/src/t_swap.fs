\ t_swap.fs — P36 cases (c), (d) and the raw-EXECUTE hole, one run, in that order so the earlier
\ evidence survives if the raw call aborts the load.
\ GUARDRAIL: the entry is called with a top-level EXECUTE, never from inside a colon word — a Forth
\ gate word loses its tail and leaves the interpreter's stack counter past SD (seg.fs, APP).
SEG-INIT
1 SEG-BEGIN
: M ( -- ) 65 EMIT ;
' M SEG-ENTRY
1 SEG-SAVE
2 SEG-BEGIN
: M2 ( -- ) 66 EMIT ;
' M2 SEG-ENTRY
2 SEG-SAVE
." (c) seg1 entry bytes after seg2 took the window: " 1 SEG-WORD RAW@ . ." (seg1's entry was 4100)" CR
." (d) seg1 entry through the gate: " 1 APP CR
." (c) seg2 in the window, executed: " 2 SEG-WORD EXECUTE ." <- B above, seg2 ran" CR
." raw EXECUTE of seg1's stale entry: [" 1 SEG-WORD EXECUTE ." ] end (silence = the hole)" CR
." still alive, resident HERE " 4 RAW@ . CR
