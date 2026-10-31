\ boot_min.fs - smallest boot layer that makes the compiler usable.
\
\ The prototype ships only primitives. DO/LOOP/IF/THEN exist only as their
\ runtime halves ((DO), (LOOP), 0BRANCH, BRANCH) plus the comma words.
\ Everything needed to *write* control flow has to be defined in Forth.
\
\ Not a shipping prelude: no number formatting, no editor, no messages.
\ This is a test fixture whose job is to prove the model closes.
\
\ Why ['] in front of each token: these words run while the enclosing
\ definition is being compiled, so the token they append has to be pushed
\ as a literal at definition time. A bare 0BRANCH there would be compiled
\ as a call instead of appended as a token.

\ --- system variable accessors (kept inside the image) ---
: HERE    4 @ ;            \ V_HERE
: LATEST  8 @ ;            \ V_LATEST
: STATE   0 @ ;            \ V_STATE
: IMMEDIATE  LATEST 2 + DUP C@ 128 OR SWAP C! ;
: BASE    12 @ ;            \ V_BASE
: HEX     16 BASE ! ;
: DECIMAL 10 BASE ! ;

\ --- conditionals ---
\ 0BRANCH operand is an absolute address; a forward branch stores HERE after.
\ GUARDRAIL: ! and W! are ( val addr -- ), addr on TOP.
\ So `HERE W!` stores HERE into the *dictionary*, not into the branch
\ placeholder: 2 bytes corrupted, branch unpatched, and the symptom is a
\ hang much later. Always: HERE SWAP W! ( val=HERE, addr=placeholder ).
\ GUARDRAIL: P02 build B - every compiled cell is 4 bytes, so branch operands
\ use `,` and `!` and the placeholder address is HERE 4 - ; a leftover `W,`
\ leaves a 2-byte hole that the interpreter then reads as a token.
\ GUARDRAIL: this file is loaded through a 80-byte line buffer; a comment over
\ 79 chars aborts the whole boot layer, not just that line.
: IF     ['] 0BRANCH ,  0 ,  HERE 4 - ;  IMMEDIATE
: THEN   HERE SWAP ! ;                   IMMEDIATE
: ELSE   ['] BRANCH , 0 ,  HERE SWAP !  HERE 4 - ;   IMMEDIATE

\ --- indefinite loops ---
: BEGIN  HERE ;                            IMMEDIATE
: UNTIL  ['] 0BRANCH , , ;                 IMMEDIATE
: AGAIN  ['] BRANCH   , , ;                IMMEDIATE
: WHILE  ['] 0BRANCH , 0 , HERE 4 - ;      IMMEDIATE
: REPEAT SWAP ['] BRANCH , ,  HERE SWAP ! ; IMMEDIATE

\ --- counted loops ---
\ (DO) has no inline operand; the body starts right after its token.
\ (LOOP) carries the backward target as a 4-byte operand, so DO leaves
\ HERE on the compile-time stack for LOOP to consume.
: DO     ['] (DO)    ,  HERE ;             IMMEDIATE
: LOOP   ['] (LOOP)  ,  , ;                IMMEDIATE
: +LOOP  ['] (+LOOP) ,  , ;                IMMEDIATE

\ --- small words so tests can be written plainly ---
: ?DUP   DUP IF DUP THEN ;
: 2DUP   OVER OVER ;
: NIP    SWAP DROP ;
: TUCK   SWAP OVER ;
: 1+     1 + ;
: 1-     1 - ;
: 2*     2 * ;
: NEGATE 0 SWAP - ;
: =      - 0= ;
: <>     = 0= ;
: >      SWAP < ;
: 0<     0 < ;
: 0>     0 SWAP < ;
: NOT    0= ;
\ / and MOD must precede 2/ and */ : the prototype has no forward refs.
: /      /MOD SWAP DROP ;
: MOD    /MOD DROP ;
: 2/     2 / ;
: */     SWAP ROT * SWAP / ;
