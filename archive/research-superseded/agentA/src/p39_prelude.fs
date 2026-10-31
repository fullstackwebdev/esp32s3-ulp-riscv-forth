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
\ GUARDRAIL: P51 moved the immediate flag from bit 7 of the header's length byte to bit 0 of the
\ 4-byte header key, so the old `LATEST 2 + DUP C@ 128 OR SWAP C!` wrote into the middle of the hash and
\ made the word it had just defined unfindable — the symptom was `IF?` three lines later, not an error
\ at IMMEDIATE. The header is one cell now: read it, set bit 0, write it back.
: IMMEDIATE  LATEST DUP @ 1 OR SWAP ! ;

\ GUARDRAIL: P38 fix 1 — IF/ELSE used `['] 0BRANCH ,` for the branch *token*. P_COMMA writes a
\ 4-byte, 4-aligned cell (a4() + wr32) while a token is 2 bytes (cw), so the compiled stream was
\ [token][00 00][operand]: ZBRANCH's 2-byte skip landed on the filler (true path read 0x0000 as the
\ next token and executed DOCOL at address 0, rsp climbing), and its operand read fetched the filler
\ (false path jumped to 0 = return to C). The token goes out with W, (2 bytes); only the *operand*
\ placeholder/backpatch uses W, too, because ZBRANCH reads it with rd16_paged and skips 2.
: IF     ['] 0BRANCH W,  0 W,  HERE 2 - ;   IMMEDIATE
: THEN   HERE SWAP W! ;                     IMMEDIATE
: ELSE   ['] BRANCH W,   0 W,  HERE SWAP W!  HERE 2 - ;  IMMEDIATE

\ GUARDRAIL: BRANCH/0BRANCH are primitives but no compiling loop word is, so a probe step written
\ BEGIN … UNTIL cannot load against P33's prelude at all (P37 measured the parse error). Both are
\ two tokens and no operand arithmetic: UNTIL's backward operand is `HERE` at BEGIN, forward.
: BEGIN  HERE ;                             IMMEDIATE
: UNTIL  ['] 0BRANCH W,  W, ;               IMMEDIATE

: =      - 0= ;
: <>     = 0= ;
: 1+     1 + ;
\ GUARDRAIL: boot16.fs defines 1+ but not 1- ; a counted loop written with 1- dies at load time
\ (`1-?`), which costs a whole run inside a 15-minute box (P37 hit it).
: 1-     1 - ;
: NIP    SWAP DROP ;

\ ---- P39 additions: the printing word its one line needs -------------------
\ GUARDRAIL: the probe's line is `2 3 + 4 * .` but P38's prelude has no `.` — this engine's
\ primitive set is P32 D's (no `.`, no `=`, no WHILE/REPEAT). Without these three words the line
\ cannot load at all (`.?`), so they are the minimum that makes the documented line runnable.
\ VERBATIM from P34/P36's pre.fs (the paging probes' proven `.`) plus boot_min's WHILE/REPEAT with
\ P38 fix 1's W, width — nothing is invented here.
\ GUARDRAIL: WHILE/REPEAT carry W, for both the token and the operand placeholder, like IF/THEN.
\ `,` is a4()+wr32: it would write [token][00 00][operand] and every ZBRANCH would read 2 bytes late.
: WHILE  ['] 0BRANCH W,  0 W,  HERE 2 - ;   IMMEDIATE
: REPEAT SWAP ['] BRANCH W,  W,  HERE SWAP W! ;  IMMEDIATE

: . ( n -- )                      \ print signed decimal, no recursion (no name visible to itself)
  DUP 0 < IF 45 EMIT 0 SWAP - THEN
  DUP 0= IF 48 EMIT DROP EXIT THEN
  0 SWAP                          ( cnt val )
  BEGIN DUP WHILE 10 /MOD SWAP >R SWAP 1 + SWAP REPEAT DROP
  BEGIN DUP WHILE 48 R> + EMIT 1 - REPEAT DROP ;
