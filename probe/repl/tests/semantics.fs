\ SEMANTICS — the storage words, pinned. Written because a benchmark "found an engine defect" that was
\ really this idiom mistake (F-119 retracted, E-081 amended): `HERE CONSTANT X 0 ,` does NOT create a
\ variable. HERE is read BEFORE the header exists, so X's value is the address of X's own HEADER; `@` there
\ returns header bytes, and `!` there corrupts the dictionary. `CREATE X 0 ,` names the BODY and is the idiom.
\ Every value here is deterministic on the host build (MEMSZ 2048, fixed prelude).
\ GUARDRAIL: this file is the reason nobody has to rediscover the trap. If one of these lines changes
\ behaviour, that is a real semantic change and the golden file must be re-derived deliberately.
\ 1. a CREATE'd variable: store, read back
CREATE V 0 ,
42 V ! V @ .
\ 2. the same read inside a colon word, and inside a loop (DOCVAR from a compiled context)
: RD V @ ;
RD .
: LP 0 BEGIN V @ DROP 1+ DUP 3 < 0= UNTIL . ;
LP
\ 3. a CONSTANT from a compiled context, once and in a loop (this is what F-119 wrongly claimed was broken)
7 CONSTANT K7
: RC K7 ;
RC .
: LC 0 BEGIN K7 DROP 1+ DUP 3 < 0= UNTIL . ;
LC
\ 4. the trap itself: `HERE CONSTANT` yields the header address, so @ is not a fresh zero cell
HERE CONSTANT TRAP 0 ,
TRAP @ 0= .
