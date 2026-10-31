\ MEMORY — fill a 16-cell buffer with 0..15, then read it back and sum it.
\ The machine's only "bandwidth": no DMA, no block move, no ALLOT, so this is a !/@ loop.
\ Expected sum 0+1+...+15 = 120.
\
\ GUARDRAIL: the order is RES, then CREATE, then RES. CREATE sets the name's body address to V_HERE at
\ that moment, so a buffer created BEFORE the word that reserves it overlaps that word's own code — measured:
\ the first store overwrote the loop doing the storing. Creating after RES, and calling RES after that, puts
\ the 16 cells immediately above RES's body and nothing else moves.
\ GUARDRAIL: `HERE CONSTANT BUF 0 ,` is NOT a variable — HERE is read before the header exists, so the
\ constant's value is its own HEADER address (measured: VB=590, VB@ = 38666242, header bytes). CREATE is the
\ variable idiom; see tests/semantics.fs, which pins this so it is never rediscovered.
: RES 16 0 BEGIN DUP , 1+ DUP 16 < 0= UNTIL DROP ;
CREATE BUF
RES
: MFILL 0 BEGIN DUP DUP 4 * BUF + ! 1+ DUP 16 < 0= UNTIL DROP ;
: MSUM  0 0 BEGIN DUP 4 * BUF + @ ROT + SWAP 1+ DUP 16 < 0= UNTIL DROP . ;
MFILL
MSUM
