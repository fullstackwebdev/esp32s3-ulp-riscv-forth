\ control.fs — the smallest compiler prelude, because the engine ships only runtime halves.
\
\ GUARDRAIL: tokens are 2 bytes (`vm_enter`: w = rd16(ip); ip += 2) and so are branch operands, so a
\ control word must append with the same width the C compiler uses. boot_min.fs from P26/P32/P33
\ appends 4-byte tokens and 4-byte branch operands (`,`, `HERE 4 -`); loaded into this engine its IF
\ patches the wrong half of a cell and every conditional silently mis-branches (P34 found it: P33's
\ host build never ran, which is why P33 has no RESULT.md). TOK/PH below are 2 bytes each and are the
\ only things the control words use.
\ GUARDRAIL: W, is not in the required primitive set, so a 2-byte append is two C, calls; and a
\ 2-byte placeholder's patch address is HERE 2 - , not HERE 4 - .

: HERE    4 @ ;
: LATEST  8 @ ;
: STATE   0 @ ;
: IMMEDIATE  LATEST 2 + DUP C@ 128 OR SWAP C! ;

\ GUARDRAIL: W, is the 2-byte append (cw) and W! patches a 2-byte operand; `,` is 4-byte and
\ 4-byte aligned (a4), so a `,` here mis-branches every conditional. W,/W! are NOT in D's
\ required set (P32) — the compiler words need them and the subset must pay for them.
: TOK ( t -- ) W, ;                  \ append a 2-byte token
: PH  ( -- a )  0 W, HERE 2 - ;      \ append a 2-byte placeholder, leave its address

: IF     ['] 0BRANCH TOK PH ;        IMMEDIATE
: THEN   HERE SWAP W! ;              IMMEDIATE
\ GUARDRAIL: ELSE holds two placeholders (the IF's and its own). `HERE SWAP W!` patches the wrong one
\ — it leaves the IF's operand 0 and sends the else-part 2 bytes past its first token, so a word with
\ IF..ELSE..THEN returns its argument instead of the value (P34 lost an hour here). ROT first.
: ELSE   ['] BRANCH TOK PH  HERE ROT W! ;  IMMEDIATE
: BEGIN  HERE ;                      IMMEDIATE
: UNTIL  ['] 0BRANCH TOK W, ;        IMMEDIATE
: AGAIN  ['] BRANCH   TOK W, ;       IMMEDIATE
: WHILE  ['] 0BRANCH TOK PH ;        IMMEDIATE
: REPEAT SWAP ['] BRANCH TOK W,  HERE SWAP W! ;  IMMEDIATE

: ?DUP   DUP IF DUP THEN ;
: 2DUP   OVER OVER ;
: NIP    SWAP DROP ;
: 1+     1 + ;
: 1-     1 - ;
