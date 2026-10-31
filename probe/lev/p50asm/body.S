/* body.S — P51: transliterate GCC's body, then remove what it cannot.
 * GUARDRAIL: this is the answer to "asm can never lose": you cannot, if you START from GCC's instruction
 * sequence. Writing bodies from scratch (registry conventions, wrap macros) is what produced the 39 B/body
 * measurement in E-069 — that was a different, worse program, not a hand-optimisation of the same one.
 * Every instruction below is either copied from vm_enter's ADD body or a strictly cheaper replacement of a
 * group of them. Anything not justified here belongs back in C.
 */
    .text
    .option rvc

/* GCC's ADD body computes the TOS address and the NOS address independently:
 *   andi/addi/slli/add  (TOS)   + lw
 *   andi/addi/slli/add  (NOS)   + lw   -> then add, then a store, then sp-1 and another mask
 * A shared base removes the second address computation: NOS is TOS-4 unless sp wraps at 0.
 */
    .globl a_add
a_add:                                  /* a0 = &V, s2 = &DS[tos], s3 = sp  (TOS ptr convention) */
    lw    t0, 0(s2)                     /* b  */
    addi  t1, s2, -4                    /* NOS = TOS-4 ... */
    andi  t2, s3, 15                    /* unless sp & 15 == 0, where it wraps to DS[15] */
    bnez  t2, 1f
    addi  t1, a0, 60
1:  lw    t2, 0(t1)                     /* a  */
    add   t0, t0, t2                    /* a+b */
    sw    t0, 0(t1)                     /* store at the new TOS */
    addi  s3, s3, -1
    sb    s3, 128(a0)
    ret
