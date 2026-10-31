/* proto.S — P48: price hand-written primitive bodies that use a TOS POINTER instead of an index.
 *
 * The C engine addresses the stack as ds[(sp-1) & (SD-1)], so every operand access costs
 *   andi + addi + slli + add + lw  (5 instructions). With a register pointing AT the top cell,
 * the same access is `lw t0, 0(s2)` (1 instruction) and push/pop are `addi s2, s2, ±4`.
 * RISC-V has no scaled addressing, so a compiler cannot discover this transformation.
 *
 * GUARDRAIL: this file exists to be MEASURED, not run. It omits the wrap guard and the token fetch on
 * purpose; the point is bytes-per-body under the two conventions, measured against the same GCC output.
 */
    .text
    .option rvc

/* convention: s2 = pointer to TOS, VALID for the prototype */
    .globl a_dup
a_dup:                          /* ( a -- a a ) */
    lw    t0, 0(s2)
    sw    t0, 4(s2)
    addi  s2, s2, 4
    ret

    .globl a_drop
a_drop:                         /* ( a -- ) */
    addi  s2, s2, -4
    ret

    .globl a_swap
a_swap:                         /* ( a b -- b a ) */
    lw    t0, 0(s2)
    lw    t1, -4(s2)
    sw    t0, -4(s2)
    sw    t1, 0(s2)
    ret

    .globl a_over
a_over:                         /* ( a b -- a b a ) */
    lw    t0, -4(s2)
    sw    t0, 4(s2)
    addi  s2, s2, 4
    ret

    .globl a_add
a_add:                          /* ( a b -- a+b ) */
    lw    t0, 0(s2)
    lw    t1, -4(s2)
    add   t0, t0, t1
    sw    t0, -4(s2)
    addi  s2, s2, -4
    ret

    .globl a_rot
a_rot:                          /* ( a b c -- b c a ) */
    lw    t0, 0(s2)
    lw    t1, -4(s2)
    lw    t2, -8(s2)
    sw    t0, -4(s2)
    sw    t1, -8(s2)
    sw    t2, 0(s2)
    ret
