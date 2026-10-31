\ boot37.fs - P37: boot16.fs with the branch *token* emitted by W, instead of , and BEGIN/UNTIL added.
\
\ GUARDRAIL: in this engine a token is 2 bytes (cw/W,) but `,` writes a 4-byte cell (P_COMMA does
\ a4() + wr32). boot16.fs's IF is `['] 0BRANCH , 0 W, HERE 2 -`, so the compiled stream is
\ [0BRANCH][0000][operand][body]: ZBRANCH's 2-byte skip lands on the zero filler (true) and its
\ rd16 operand read fetches the filler (false). Emit the token with W, so the operand sits exactly
\ where ZBRANCH reads and skips it — that is the only difference between this file and boot16.fs.
\
\ GUARDRAIL: HERE/LATEST/STATE are not primitives in this engine — they are system variables
\ inside mem[] (V_HERE 4, V_LATEST 8, V_STATE 0). A prelude that calls HERE without defining it
\ dies on the first IMMEDIATE word (P33 measured it).
: HERE     4 @ ;
: LATEST   8 @ ;
: STATE    0 @ ;
: IMMEDIATE  LATEST 2 + DUP C@ 128 OR SWAP C! ;

: IF     ['] 0BRANCH W,  0 W,  HERE 2 - ;  IMMEDIATE
: THEN   HERE SWAP W! ;                    IMMEDIATE
: ELSE   ['] BRANCH W,   0 W,  HERE SWAP W!  HERE 2 - ;  IMMEDIATE
: BEGIN  HERE ;                            IMMEDIATE
: UNTIL  ['] 0BRANCH W,  W, ;              IMMEDIATE

: =      - 0= ;
: <>     = 0= ;
: 1+     1 + ;
: 1-     1 - ;   \ GUARDRAIL: boot16.fs defines 1+ but not 1-, and a counted spin written with 1- dies
                 \ at load time — the missing word costs a whole run inside a 15-minute box.
: NIP    SWAP DROP ;
