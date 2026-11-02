: SP ( -- ) 32 EMIT ;
: ESC ( -- ) 27 EMIT ;
: CSI ( -- ) 91 EMIT ;
: OF ( -- ) ESC CSI 48 EMIT 109 EMIT ;
: IV ( -- ) ESC CSI 55 EMIT 109 EMIT ;
: CL ( -- ) ESC CSI 50 EMIT 74 EMIT ;
: HM ( -- ) ESC CSI 72 EMIT ;
: DG ( n -- ) 15 AND 48 + EMIT ;
( GUARDRAIL LF keeps the column, so every line ends CR LF, hence no cursor addressing here )
: NL ( -- ) 13 EMIT 10 EMIT ;
: BAR ( -- ) 0 BEGIN DUP 70 < WHILE SP 1+ REPEAT DROP ;
: HD ( -- ) CL HM IV BAR 13 EMIT ." MAIL" MAIL_ST @ IF MAIL_ST 4 + @ DG THEN OF ;
: FT ( -- ) NL OF MAIL_ST @ IF ." n/p  q back" ELSE ." j/k  Enter  q shelf" THEN ;
( GUARDRAIL view and page are two cells for one number, so MAILSB is their only writer )
: MAILSB ( p -- ) DUP MAIL_ST 4 + ! MAIL_ST ! ;
( GUARDRAIL item i is line 1+i of page 0, block 81+i; line 0 is the heading, never inverted )
: MK ( r -- ) 1+ MAIL_ST 8 + @ = MAIL_ST @ 0= AND IF IV ELSE OF THEN ;
: LN ( b r -- b r ) NL DUP MK OVER OVER + BLOCK 70 TYPE ;
: PG ( p -- ) 8 * 80 + 0 BEGIN DUP 8 < WHILE LN 1+ REPEAT DROP DROP ;
( GUARDRAIL no > here, so the quit test swaps operands; view 3 is normalised through MAILSB )
: DR ( -- ) 2 MAIL_ST @ < IF 0 MAILSB THEN HD MAIL_ST 4 + @ PG FT 0 EMIT ;
: OP ( -- ) MAIL_ST 8 + @ 1+ MAILSB ;
: JD ( -- ) MAIL_ST 8 + @ 0= IF 1 MAIL_ST 8 + ! THEN ;
: KU ( -- ) MAIL_ST 8 + @ IF 0 MAIL_ST 8 + ! THEN ;
: NX ( -- ) MAIL_ST 4 + @ 2 < IF MAIL_ST 4 + @ 1+ MAILSB THEN ;
: PV ( -- ) 1 MAIL_ST 4 + @ < IF MAIL_ST 4 + @ 1- MAILSB THEN ;
: K0 ( -- c ) BEGIN KEY DUP -1 = WHILE DROP REPEAT ;
( GUARDRAIL every key arm EXITs so j cannot fall into the Enter arm, which is lint R3 )
: LL ( -- ) K @ 106 = IF JD EXIT THEN K @ 107 = IF KU EXIT THEN ;
: KL ( -- ) LL K @ 113 = IF 3 MAIL_ST ! EXIT THEN K @ 13 = IF OP THEN ;
: KK ( -- ) K @ 113 = IF 0 MAILSB EXIT THEN K @ 110 = IF NX EXIT THEN K @ 112 = IF PV THEN ;
: KS ( -- ) MAIL_ST @ IF KK ELSE KL THEN ;
: MAIL1 ( -- ) BEGIN DR K0 K ! KS 2 MAIL_ST @ < UNTIL SHELF CHAIN ;
