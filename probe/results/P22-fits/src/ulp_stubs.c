/* ulp_stubs.c - P01 host-side stub for the uforth engine ULP build.
 *
 * The engine's only public symbol is forth_quit(); interpret() is static, so main() has to live in
 * the same translation unit as the engine. This file therefore #includes the verbatim copy of
 * uforth.c that sits next to it, and adds the three platform hooks plus main().
 *
 * Every symbol defined below (pl_key, pl_emit, pl_hw, main) is "stub" and is reported separately so
 * that its bytes can be subtracted from the linked totals. See RESULT.md.
 *
 * GUARDRAIL: interpret() is static in uforth.c, so a separate stub TU cannot call it — #include the
 * engine instead of adding an accessor, because uforth.c is the frozen baseline and must not be edited.
 */

#include "uforth.c"

/* Output ring: the placeholder must be a real store to a global ring head, not a no-op, otherwise
 * the compiler turns pl_emit() into an empty function and the engine's EMIT/TYPE paths stop being
 * costed the way the design pays for them. */
static volatile u32 ring_head;

/* P22: the stub's private 64 B ring is gone — pl_emit now feeds the engine's own 256 B out_ring
 * (P04's measured O), so the output ring is a real budget line instead of a 64 B placeholder that
 * understated it by 192 B.  GUARDRAIL: the store must stay a real store to a global head, not a
 * no-op — the compiler then deletes pl_emit's body and the EMIT/TYPE paths stop being costed. */
void pl_emit(int c)
{
    out_ring[ring_head & (sizeof out_ring - 1)] = (u8)c;
    ring_head++;
}

/* -1 = "no key pressed"; the engine pushes it as a cell, exactly like a real empty caller. */
int pl_key(void)
{
    return -1;
}

/* op codes as documented in uforth.c: 0 gpio_get 1 gpio_set 2 adc 3 ms 4 wake 5 key? */
u32 pl_hw(int op, u32 a, u32 b)
{
    (void)op; (void)a; (void)b;
    return 0;
}

/* Seed one short line and interpret it once, so the outer interpreter (word/find/number) is on the
 * call graph and survives --gc-sections. The image is never executed by this probe: it is only
 * linked and measured, so forth_quit() stays unreachable and is collected. */
int main(void)
{
    static const char seed[] = "12 34 +";
    u8 i;

    for (i = 0; seed[i] && i < TIBSZ - 1; i++) tib[i] = (u8)seed[i];
    tl = i; ti = 0;

#ifndef P01_STUB_ONLY
    /* GUARDRAIL: interpret() is static, so GCC inlines the whole engine into main and "subtract the
     * stub" stops working by symbol -- build this same file with -DP01_STUB_ONLY to get a control
     * image whose only content is the stub, and subtract that instead of guessing a symbol size. */
    interpret();
#endif
    /* GUARDRAIL: every array on the 4.3 budget lines has to be touched, or -fdata-sections +
     * --gc-sections drops it and .bss shrinks by that line — a silent under-report of the pool.
     * The stores go through volatiles for the same reason: a plain store to a static array whose
     * address never escapes is dead-store-eliminated together with the array (measured: the first
     * build of this file lost 728 B of budget lines that way and still reported "fits"). */
    *(volatile u8 *)&cmd_ring[0] = (u8)ring_head;
    *(volatile u8 *)&mailbox[0] = (u8)ring_head;
    *(volatile u8 *)&vm_state_reserve[0] = out_ring[ring_head & (sizeof out_ring - 1)];
    *(volatile u8 *)&ptab_lru_reserve[0] = (u8)ring_head;
    return ring_head ? 0 : 0;
}
