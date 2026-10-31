\ Wild-address regression: every accessor that takes an address off the DATA stack must still answer an
\ out-of-range pointer with `junk`/0 and must not touch mem[]. Added for the unchecked-accessor variants
\ (TASK 2): UC_FOLD moves the check from inside rd16/wr16/rd32/wr8 into the checked call sites, so `!`
\ and `@` are exactly where that refactor can go wrong, and no suite.fs row addresses anything wild.
\ GUARDRAIL: `!` and `C!` are ( val addr -- ), addr on TOP — `100000 7 !` stores 100000 into address 7
\ (V_STATE/header territory) and the symptom is `+?` on the NEXT line, not an error here. Written the
\ wrong way round this test "proves" the engine broken; it was written wrong the first time.
\ GUARDRAIL: keep the arithmetic after the wild stores in the same file — a wild store that does land
\ inside mem[] corrupts a definition, and the parse error is the only evidence it will leave.
7 100000 !
100000 @ .
-1 C@ .
7 100000 C!
100000 C@ .
4096 @ .
2 3 + .
: WILD2 6 7 * ;
WILD2 .
\ GUARDRAIL: `-1 @` is deliberately ABSENT. rd16's guard is `a + 1u < MEMSZ`, and for a = 0xFFFFFFFF the
\ addition wraps to 0, so the test PASSES and the load runs at mem - 1. On the host that is a segfault; on
\ the ULP it reads one byte below mem[]. Same one-instruction fix as the check it replaces (test
\ `a < MEMSZ - 1`), but it is a change to the shipping reader and is reported, not made, here.
