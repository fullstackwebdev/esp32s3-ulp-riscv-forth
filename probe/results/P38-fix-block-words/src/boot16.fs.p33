\ boot16.fs - P33: the control layer for the 16-bit-token engine, corrected from boot_min.fs.
\
\ GUARDRAIL: boot_min.fs is P02-era: its IF/THEN emit a 4-byte branch operand (`0 ,` + `HERE 4 -`),
\ but P27's engine reads the operand with rd16_paged() and ZBRANCH skips 2 bytes. Loading boot_min.fs
\ on this engine compiles a branch whose target is 2 bytes past the truth, and the *symptom is a hang*
\ in the first word that branches — measured on the host build before this file existed. W, is the
\ 2-byte comma: use it for every operand the engine reads with rd16.
\ GUARDRAIL: W! and ! are ( val addr -- ): addr on TOP. `HERE W!` would write HERE into the
\ dictionary instead of into the placeholder (boot_min's own note, still true).

\ GUARDRAIL: HERE/LATEST/STATE are not primitives in this engine — they are system variables
\ inside mem[] (V_HERE 4, V_LATEST 8, V_STATE 0). A prelude that calls HERE without defining it
\ dies on the first IMMEDIATE word; P33's host build showed exactly that (`HERE?` at line 11).
: HERE     4 @ ;
: LATEST   8 @ ;
: STATE    0 @ ;
: IMMEDIATE  LATEST 2 + DUP C@ 128 OR SWAP C! ;

: IF     ['] 0BRANCH ,  0 W,  HERE 2 - ;   IMMEDIATE
: THEN   HERE SWAP W! ;                    IMMEDIATE
: ELSE   ['] BRANCH ,   0 W,  HERE SWAP W!  HERE 2 - ;  IMMEDIATE

: =      - 0= ;
: <>     = 0= ;
: 1+     1 + ;
: NIP    SWAP DROP ;
