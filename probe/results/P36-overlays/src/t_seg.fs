\ t_seg.fs — P36's five execution proofs, host build, against the fake block server.
\ GUARDRAIL: every entry into overlay code goes through APP (the directory gate). Spelling a raw xt
\ and calling EXECUTE instead is the hole t_raw.fs demonstrates — the proofs below must not use it,
\ or they would test a path the design does not offer and pass because nothing checks it.
: TF ( f -- ) IF ." PASS " ELSE ." FAIL " THEN ;

." == P36 overlays: five proofs ==" CR
SEG-INIT
." SEG-BASE " SBASE @ . ." resident HERE " HERE@ . CR

\ ---- segment 1: compiled into the fixed window, one word calls a resident word ----
1 SEG-BEGIN
: SQ ( n -- n*n ) DUP * ;
: MAIN ( -- ) 7 SQ 49 = IF ." A-OK " ELSE ." A-BAD " THEN ;
' MAIN SEG-ENTRY
." seg1 emitted " HERE@ SBASE @ - . ." bytes" CR
CREATE TOK 0 ,
' MAIN 14 + RAW@ TOK !
." (e) token in MAIN for the resident = : " TOK @ . ." xt of = : " ' = . CR
." (e) that token is a resident address: " TOK @ SBASE @ < TF CR
1 SEG-SAVE CR

\ ---- (a)+(b): run it, clear it, load it back, run it again ----
." (a) run before save:    " 1 APP CR
SEG-CLEAR CR
." (a) reload:             " 1 SEG-LOAD CR
." (a)+(b) run after reload: " 1 APP CR
\ GUARDRAIL: a top-level `' =` overflows the 16-cell stack (sp>=SD); the xt is shown above.
." (e) same token after reload: " 1 SEG-WORD 14 + RAW@ . ." unchanged: " 1 SEG-WORD 14 + RAW@ TOK @ = TF CR
." (e) still equals xt of = : " 1 SEG-WORD 14 + RAW@ ' = = TF CR

\ ---- (c): a second overlay takes the same window, and the first one's bytes are gone ----
CREATE OLDTOK 0 ,
1 SEG-WORD 6 + RAW@ OLDTOK !          \ the slot in MAIN that held the token for SQ
." (c) seg1 token for SQ, before the swap: " OLDTOK @ . CR
2 SEG-BEGIN
: M2 ( -- ) ." SEG2 " ;
' M2 SEG-ENTRY
2 SEG-SAVE CR
." (c) the same address now holds: " 1 SEG-WORD 6 + RAW@ . CR
." (c) seg1 bytes gone: " 1 SEG-WORD 6 + RAW@ OLDTOK @ = 0= TF CR
." (c) the second overlay runs: " 2 APP CR

\ ---- (d): the first overlay's entry, called from resident code, is refused by name ----
." (d) seg1 entry after the swap: " 1 APP CR

\ ---- the dangerous case: an overlay calling another overlay ----
3 SEG-BEGIN
: M3 ( -- ) ." SEG3 " 1 SEG-CALL ." (nothing of seg1 ran) " ;
' M3 SEG-ENTRY
3 SEG-SAVE CR
." overlay 3 calls segment 1: " 3 APP CR
." and the resident call path still works: " 2 APP CR
." resident HERE at the end " HERE@ . ." stays below SEG-BASE: " HERE@ SBASE @ < TF CR
." transfers " FXFERS @ . CR
