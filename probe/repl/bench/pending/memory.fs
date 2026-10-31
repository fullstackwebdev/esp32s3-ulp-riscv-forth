\ PENDING - blocked by an ENGINE defect this benchmark found (E-081): calling a CONSTANT (a DOCON word)
\ from inside a colon definition underflows the stack. Minimal repro:
\   0 BLOCK CONSTANT KONST
\   : T1 0 BEGIN KONST DROP 1+ DUP 20 < 0= UNTIL DROP . ;
\   T1   ->  "stack underflow"
\ A colon word called the same way is fine, so it is specific to DOCON. This file is kept because it IS the
\ reproduction; the memory-bandwidth NUMBER stays unmeasured until DOCON is fixed, because inventing one
\ from a failing run is exactly the kind of number this project has been burned by.
\ MEMORY — fill a 16-cell scratch buffer with 0..15, then read it back and sum it.
\ Measures per-cell store AND load cost. There is no DMA, no block move and no ALLOT, so this is a !/@
\ loop and nothing else: the machine's real "bandwidth".
\ GUARDRAIL: the scratch lives in the CODE area (HERE + `,`), not in the block window. With blocks on,
\ HDRTOP = BLKADR, so the window's first byte IS where the header area starts living: `C!` at
\ BLKADR+0 corrupted dictionary headers and the next lookup dispatched garbage (measured: ERR_STACK).
\ GUARDRAIL: CONSTANT takes its value FROM THE STACK, so `\ GUARDRAIL: reserve FIRST, then capture the
\ base. `HERE CONSTANT MBUF` followed by the words that use it
\ points MBUF INTO THEIR OWN CODE — the buffer and the definitions occupy the same bytes, so the first store
\ overwrote the loop that was storing and the next iteration dispatched garbage (measured: ERR_STACK on a
\ four-cell fill). RESERVE pushes the base it used and leaves it on the stack, and CONSTANT takes it.
\ GUARDRAIL: no `16` before the `0`. The limit is compared as a literal inside the body, so pushing it
\ once outside leaves it on the stack forever — and the next CONSTANT took THAT (16) as the buffer address,
\ which put the buffer in the interpreter's own variables. Measured: MBUF . -> 16.
: RESERVE HERE 0 BEGIN DUP , 1+ DUP 16 < 0= UNTIL DROP ;
RESERVE CONSTANT MBUF
: MEMFILL 0 0 BEGIN DUP 4 * MBUF + ! SWAP OVER + SWAP 1+ DUP 16 < 0= UNTIL DROP ;
: MEMSUM  0 0 BEGIN DUP 4 * MBUF + @ ROT + SWAP 1+ DUP 16 < 0= UNTIL DROP . ;
MBUF .
MEMFILL
MEMSUM
