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
\ GUARDRAIL: BASE pushes the ADDRESS of V_BASE (12), never its contents.
\ With `12 @`, HEX stored 16 into the word at V_LATEST+2, corrupting the
\ dictionary link chain; two probes later it looked like a paging hang.
\ Any system-variable accessor must return the address.
\ (Also: comments here must stay under 80 bytes - the loader rejects longer
\ lines, which is exactly the input-buffer defect in 03-prototype-review D10.)
: BASE    12 ;              \ V_BASE address, not its value
: HEX     16 BASE ! ;
: DECIMAL 10 BASE ! ;

\ --- conditionals ---
\ 0BRANCH operand is an absolute address; a forward branch stores HERE after.
\ GUARDRAIL: ! and W! are ( val addr -- ), addr on TOP.
\ So `HERE W!` stores HERE into the *dictionary*, not into the branch
\ placeholder: 2 bytes corrupted, branch unpatched, and the symptom is a
\ hang much later. Always: HERE SWAP W! ( val=HERE, addr=placeholder ).
: IF     ['] 0BRANCH W,  0 W,  HERE 2 - ; IMMEDIATE
: THEN   HERE SWAP W! ;                   IMMEDIATE
: ELSE   ['] BRANCH W, 0 W,  HERE SWAP W!  HERE 2 - ; IMMEDIATE

\ --- indefinite loops ---
: BEGIN  HERE ;                            IMMEDIATE
: UNTIL  ['] 0BRANCH W, W, ;               IMMEDIATE
: AGAIN  ['] BRANCH   W, W, ;              IMMEDIATE
: WHILE  ['] 0BRANCH W, 0 W, HERE 2 - ;    IMMEDIATE
: REPEAT SWAP ['] BRANCH W, W,  HERE SWAP W! ; IMMEDIATE

\ --- counted loops ---
\ (DO) has no inline operand; the body starts right after its token.
\ (LOOP) carries the backward target as a 2-byte operand, so DO leaves
\ HERE on the compile-time stack for LOOP to consume.
: DO     ['] (DO)    W,  HERE ;            IMMEDIATE
: LOOP   ['] (LOOP)  W,  W, ;              IMMEDIATE
: +LOOP  ['] (+LOOP) W,  W, ;              IMMEDIATE

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
