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
' MAIN 12 + RAW@ TOK !
." (e) token in MAIN for the resident = : " TOK @ . ." xt of = : " ' = . CR
." (e) that token is a resident address: " TOK @ SBASE @ < TF CR
1 SEG-SAVE CR

\ ---- (a)+(b): run it, clear it, load it back, run it again ----
1 APP
1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1
