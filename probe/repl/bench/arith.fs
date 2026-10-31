\ ARITH — sum of i*i, i = 1..1000, printed modulo 1 000 003.
\ Base case for integer throughput: one multiply and one add per iteration, plus loop overhead.
\ GUARDRAIL: the loop MUST be inside a colon definition. The prelude's BEGIN/UNTIL are COMPILE-ONLY
\ (immediate words that emit branches), so at top level they do not loop at all — measured: the same body
\ typed at the prompt ran once and printed a plausible wrong number, 324901 instead of 832501.
: ARITH 0 1 BEGIN DUP DUP * ROT + SWAP 1+ DUP 1001 < 0= UNTIL DROP 1000003 /MOD DROP . ;
ARITH
