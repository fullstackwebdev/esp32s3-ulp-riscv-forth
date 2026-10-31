\ exp_b.fs - P38 (b): words whose compiled bodies are read back token by token. NONE of these is
\ executed (B4 would spin): the driver disassembles them from mem[] and checks every branch operand
\ against the token boundaries it walked.
: B0 0 IF THEN ;
: B1 0 IF ELSE THEN ;
: B2 1 IF 66 EMIT ELSE 67 EMIT THEN ;
: B3 0 IF 1 IF 65 EMIT ELSE 66 EMIT THEN ELSE 2 IF 67 EMIT THEN THEN ;
: B4 BEGIN 0 UNTIL ;
