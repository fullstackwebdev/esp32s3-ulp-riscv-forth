\ calc_logic.fs - the calculator's arithmetic, as words, on the host engine (docs/26 gate G2-logic).
\
\ GUARDRAIL: the bodies below are the PHASE's bodies, copied verbatim from examples/apps/calc/calc1.fs. A phase is a
\ separate image and the machine has no INCLUDE, so the test cannot load the phase - the copy is the contract's own
\ price (docs/26: "the pure logic ... as words"). If you change a body in calc1.fs, change it here in the same commit;
\ the grid test (tools/screen.py) is what catches a drift in the phase, this file is what pins the arithmetic.
\
\ GUARDRAIL: CALC_ST is 5 cells and a cell is 4 BYTES. `CALC_ST 1 + @` reads across two cells (measured 335544320),
\ which is what the first draft of the phase did - index with `4 *` and nothing else.
CREATE CALC_ST 0 , 0 , 0 , 0 , 0 ,
CREATE TAPE 0 , 0 , 0 , 0 ,
: CS ( n -- a ) 4 * CALC_ST + ;
: TP ( n -- a ) 4 * TAPE + ;
: DGT ( c -- ) 48 - 0 CS @ 10 * + 0 CS ! ;
: SG ( n -- ) 0 CS @ * 1 CS @ + 1 CS ! ;
: MUL ( -- ) 1 CS @ 0 CS @ * 1 CS ! ;
: DIV ( -- ) 1 CS @ 0 CS @ /MOD SWAP DROP 1 CS ! ;
: AP1 ( -- ) 2 CS @ 43 = IF 1 SG THEN 2 CS @ 45 = IF -1 SG THEN ;
: AP2 ( -- ) 2 CS @ 42 = IF MUL THEN 2 CS @ 47 = IF DIV THEN ;
: AP ( -- ) 2 CS @ IF AP1 AP2 ELSE 0 CS @ 1 CS ! THEN ;
: EQ ( -- ) AP 1 CS @ 4 CS @ 4 * TAPE + ! 4 CS @ 1+ 3 AND 4 CS ! 0 0 CS ! ;
: OP ( c -- ) AP 2 CS ! 0 0 CS ! ;
: CLR ( -- ) 0 0 CS ! 0 1 CS ! 0 2 CS ! 0 4 CS ! ;
\ GUARDRAIL: a value typed as a number still has to reach the cells through DGT, or the test would prove the
\ test's own arithmetic instead of the phase's digit accumulation (measured: 12 -> cells as 3, 4, ... wrongly).
: NUM ( n -- ) DUP 10 < IF 48 + DGT ELSE DUP 10 /MOD SWAP DROP 48 + DGT 10 /MOD DROP 48 + DGT THEN ;
: T ( n -- ) . 58 EMIT 32 EMIT ;
: P ( n -- ) . 32 EMIT ;
: A1 ( -- ) CLR 12 NUM 43 OP 34 NUM EQ 1 T 1 CS @ P 0 CS @ P 0 TP @ P 4 CS @ P ;
: A2 ( -- ) CLR 100 NUM 45 OP 7 NUM EQ 2 T 1 CS @ P ;
: A3 ( -- ) CLR 9 NUM 42 OP 9 NUM EQ 3 T 1 CS @ P ;
: A4 ( -- ) CLR 22 NUM 47 OP 7 NUM EQ 4 T 1 CS @ P ;
: A5 ( -- ) CLR 8 NUM 47 OP 0 NUM EQ 5 T 1 CS @ P ;
: A6 ( -- ) CLR 1 NUM 43 OP 2 NUM 42 OP 3 NUM EQ 6 T 1 CS @ P ;
: A7 ( -- ) CLR 12 NUM 43 OP 34 NUM EQ 43 OP 5 NUM EQ 7 T 1 CS @ P ;
: ZR ( -- ) 0 0 CS ! 0 1 CS ! 0 2 CS ! ;
: ST ( n -- ) ZR NUM 43 OP 0 NUM EQ ;
: A8 ( -- ) 0 4 CS ! 1 ST 2 ST 3 ST 4 ST 8 T 4 CS @ P 0 TP @ P 1 TP @ P 2 TP @ P 3 TP @ P ;
: A9 ( -- ) 0 4 CS ! 1 ST 2 ST 3 ST 4 ST 5 ST 9 T 4 CS @ P 0 TP @ P ;
: A10 ( -- ) CLR 12 NUM 43 OP 34 NUM EQ 0 4 CS ! 4 CS @ TP @ DUP 0 CS ! 1 CS ! 10 T 0 CS @ P 1 CS @ P ;
: A11 ( -- ) CLR 123 NUM 11 T 0 CS @ P ;
A1 A2 A3 A4 A5 A6 A7 A8 A9 A10 A11
