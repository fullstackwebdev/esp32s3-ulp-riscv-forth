/* dispatch.S — P50: REPLACE vm_enter's loop (not be called from it).
 *
 * GUARDRAIL: measured, not assumed. The callable-per-token shape (`p50_try`) cost 368 B for seven bodies
 * against GCC's ~84 B for the same seven, because a per-token call pays a frame, a compare chain and a ret
 * for a two-instruction body (E-069). The optimisation must live at the same level as the thing it
 * replaces — the third time that rule has been the deciding factor in this project.
 *
 * The asm owns: the token fetch (with the rd16_paged bound), dispatch by id range, the per-body wrap
 * re-derivation, and the `w = mem[ip]; ip += 2` advance. It does NOT own: anything it does not implement
 * (it publishes state and returns the token so the C switch runs exactly one case), nor task retirement
 * (`ip == 0` is reported as DONE and C calls vm_task_leave).
 *
 * GUARDRAIL: the wrap check is not optional. P48's 15 B/body prototype assumed a valid TOS pointer and
 * omitted it (E-066); a store to s2+4 at index 15 lands in RS[0] and silently corrupts the return stack.
 * It costs ~5 instructions per two-operand body, which is why a realistic body is ~23 B, not 15 B.
 *
 * GUARDRAIL: MEMSZ arrives in a2, never as a literal. A hardcoded bound is a second copy of a constant
 * that already lives in ulp_repl.c, and the last time this project kept a constant in two places the
 * host wrote past the end of a ring (F-74). The bound here decides whether a token fetch is legal.
 *
 * Convention: a0 = &V, a1 = &mem, a2 = MEMSZ. Returns the token to fall back on, or 0x10000 when done.
 * s0=&V  s1=&mem  s2=&DS[tos]  s3=sp  s4=w  s5=ip
 */
    .text
    .option rvc

#define SAVE_VM                     \
    sb    s3, 128(s0)            ;  \
    sh    s4, 130(s0)            ;  \
    sh    s5, 132(s0)

#define PUSH_CELL(srcreg)           \
    sw    srcreg, 4(s2)          ;  \
    addi  s3, s3, 1              ;  \
    andi  t6, s3, 15             ;  \
    bnez  t6, 1f                 ;  \
    addi  s2, s0, 60             ;  \
    j     2f                     ;  \
1:  addi  s2, s2, 4              ;  \
2:

#define POP_CELL()                  \
    addi  s3, s3, -1             ;  \
    addi  s2, s2, -4             ;  \
    andi  t6, s3, 15             ;  \
    li    t5, 15                 ;  \
    bne   t6, t5, 3f             ;  \
    addi  s2, s0, 60             ;  \
3:

#define NOSADDR(dst)                \
    addi  dst, s2, -4            ;  \
    andi  t6, s3, 15             ;  \
    li    t5, 1                  ;  \
    bne   t6, t5, 4f             ;  \
    addi  dst, s0, 60            ;  \
4:

    .globl p50_loop
p50_loop:
    addi  sp, sp, -32
    sw    s0, 0(sp)
    sw    s1, 4(sp)
    sw    s2, 8(sp)
    sw    s3, 12(sp)
    sw    s4, 16(sp)
    sw    s5, 20(sp)
    sw    s6, 24(sp)
    mv    s0, a0
    mv    s1, a1
    addi  s6, a2, -1                 /* MEMSZ-1, the largest legal w */
    lbu   s3, 128(s0)
    addi  t0, s3, -1
    andi  t0, t0, 15
    slli  t0, t0, 2
    add   s2, s0, t0
    lhu   s4, 130(s0)                /* w */
    lhu   s5, 132(s0)                /* ip */

.Lfetch:
    /* cf = rd16_paged(w): mem[w] | mem[w+1]<<8, 0 out of range */
    bgtu  s4, s6, .Lzero
    add   t0, s4, s1
    lhu   a0, 0(t0)
    j     .Ldisp
.Lzero:
    li    a0, 0

.Ldisp:
    addi  t0, a0, -14                /* DUP..OVER are ids 14..17 */
    li    t1, 3
    bgtu  t0, t1, 5f
    slli  t0, t0, 2
    lui   t1, %hi(.Ljt)
    addi  t1, t1, %lo(.Ljt)
    add   t0, t0, t1
    lw    t0, 0(t0)
    jr    t0
5:  li    t1, 27                     /* ADD/SUB are 27..28 */
    sub   t0, a0, t1
    li    t2, 1
    bgtu  t0, t2, 6f
    slli  t0, t0, 2
    lui   t1, %hi(.Ljt2)
    addi  t1, t1, %lo(.Ljt2)
    add   t0, t0, t1
    lw    t0, 0(t0)
    jr    t0
6:  li    t1, 38                     /* ZEQ */
    beq   a0, t1, .Lzeq

    /* not ours: publish and hand the token back to C */
    SAVE_VM
    j     .Lout

.Ldup:
    lw    t0, 0(s2)
    PUSH_CELL(t0)
    j     .Lnext
.Ldrop:
    POP_CELL()
    j     .Lnext
.Lswap:
    lw    t0, 0(s2)
    NOSADDR(t1)
    lw    t2, 0(t1)
    sw    t2, 0(s2)
    sw    t0, 0(t1)
    j     .Lnext
.Lover:
    NOSADDR(t1)
    lw    t0, 0(t1)
    PUSH_CELL(t0)
    j     .Lnext
.Ladd:
    lw    t0, 0(s2)
    NOSADDR(t1)
    lw    t2, 0(t1)
    add   t0, t0, t2
    POP_CELL()
    sw    t0, 4(s2)
    j     .Lnext
.Lsub:
    lw    t0, 0(s2)
    NOSADDR(t1)
    lw    t2, 0(t1)
    sub   t0, t2, t0
    POP_CELL()
    sw    t0, 4(s2)
    j     .Lnext
.Lzeq:
    lw    t0, 0(s2)
    snez  t0, t0
    xori  t0, t0, 1
    sub   t0, zero, t0
    sw    t0, 0(s2)
    j     .Lnext

.Lnext:
    /* w = mem[ip]; ip += 2 ; ip == 0 means the machine is finished */
    addi  s5, s5, 2
    beqz  s5, .Ldone
    bgtu  s5, s6, .Lzero2
    add   t0, s5, s1
    lhu   s4, 0(t0)
    j     .Lfetch
.Lzero2:
    li    s4, 0
    j     .Lfetch
.Ldone:
    SAVE_VM
    li    a0, 0x10000
    j     .Lout
.Lout:
    lw    s0, 0(sp)
    lw    s1, 4(sp)
    lw    s2, 8(sp)
    lw    s3, 12(sp)
    lw    s4, 16(sp)
    lw    s5, 20(sp)
    lw    s6, 24(sp)
    addi  sp, sp, 32
    ret

    .section .rodata
    .align 2
.Ljt:                               /* ids 14,15,16,17 */
    .word .Ldup, .Ldrop, .Lswap, .Lover
.Ljt2:                              /* ids 27,28 */
    .word .Ladd, .Lsub
