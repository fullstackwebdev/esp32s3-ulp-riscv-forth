\ F-122 regression test. Two tasks that PAUSE must interleave: PC prints 1, yields to PD which prints 3, PD
\ yields back, PC prints 2, PD prints 4 — every digit 1..4 exactly once, in this order. Before the fix the
\ machine printed 122 or 1212 and the second task ran the first task's body.
\ ROOT CAUSE, so it is not re-introduced: vm_copy copied the VM through a u32* while W/IP are u16 — a
\ strict-aliasing violation that -O2/-Os exploited. -O0/-O1 were correct, which is how it was identified.
\ The build now passes -fno-strict-aliasing; a type-safe copy costs +68 B and would let the flag go.
\ GUARDRAIL: this test only exists because the host can be made to STEP tasks (uforth.c main does, after a
\ clean load). Without that, no host test could execute two tasks and this regression was invisible.
: PC 1 . PAUSE 2 . ;
: PD 3 . PAUSE 4 . ;
SPAWN PC SPAWN PD
