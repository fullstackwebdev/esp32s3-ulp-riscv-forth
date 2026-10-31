\ os_tasks.fs - P26 group 1: three task slots, round robin, tick, sleep.
\ GUARDRAIL: the 40-primitive engine has no ALLOT, no VARIABLE and no
\ DOES>; a variable is CREATE + one cell and space is claimed by moving
\ V_HERE. CREATE alone reserves nothing, so the next header overwrites
\ the body - reserve the cell on the same line.
: ALLOT   HERE + 4 ! ;
\ GUARDRAIL: index the pool with `3 MOD`, not `3 AND`: AND yields 0..3 and
\ slot 3 runs off the end of a 3-slot pool. MOD costs the same 2 cells.
\ Record: [xt:4][sp:4].
CREATE SLOTS 24 ALLOT
CREATE CUR 0 ,
CREATE TICK 0 ,
CREATE DIAG 0 ,            \ 0 = ok, else a named code

\ TASK ( xt i -- ) fill slot i and claim a 16-cell stack for it. No
\ free-slot scan: the pool is a fixed size and the caller owns the slot
\ numbers.
: TASK
  3 MOD 8 * SLOTS + DUP >R !
  HERE 64 ALLOT R> 4 + ! ;

\ GUARDRAIL: nothing here saves or restores dsp/rsp/ip - no primitive in
\ the 40 can, so YIELD switches the *books* only. Do not read this as a
\ working context switch; see RESULT.md.
\ GUARDRAIL: YIELD returns nothing on purpose. It used to leave the slot
\ number on the stack, and SLEEP-TICKS pushed one more slot per iteration
\ until the data stack wrapped - a leak that only shows at run time, not at
\ compile time. Every word here must be stack-neutral.
\ YIELD one tick per turn, round robin over the three slots.
: YIELD
  TICK @ 1+ DUP TICK !
  CUR @ 1+ 3 MOD DUP CUR ! ;
: PAUSE   YIELD ;
\ keep-cost of the PAUSE alias: measured 12 B headerless

\ SLEEP-TICKS ( n -- ) yield until n ticks have passed. There is no wake
\ field and no sleep state: a sleeping task is scheduled every round and
\ re-yields, which is the cost of dropping the state machine.
: SLEEP-TICKS
  TICK @ +
  BEGIN YIELD TICK @ SWAP < 0= UNTIL DROP ;
