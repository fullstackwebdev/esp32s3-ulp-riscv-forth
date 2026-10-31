/* ulp_stubs.c - P29: the shipping build. The engine TU is P27's 16-bit-token engine with P22's
 * paging, frames and budget arrays folded in; this file supplies the layer's four hooks for real
 * plus main(), and nothing else.
 *
 * GUARDRAIL: interpret() is static in uforth.c, so main() must live in the same translation unit —
 * #include the engine instead of adding an accessor, because the engine copy has to stay comparable
 * with P22/P27's measurements.
 *
 * Every symbol defined here (pl_key, pl_emit, pl_hw, pl_halt, main) is charged as the harness and
 * subtracted: build this same file with -DP29_HARNESS_ONLY for the control image.
 */
#include "uforth.c"

/* Output ring head. The store must be a real store to a global, or the compiler deletes pl_emit()'s
 * body and the EMIT/TYPE paths stop being costed (P22 measured that as a 192 B understatement).
 * GUARDRAIL: pl_emit must feed the engine's own 256 B out_ring — a private stub ring would pay for
 * output twice and hide the budget line it is supposed to charge. */
static volatile u32 ring_head;
static volatile u32 halt_status;      /* P29: pl_halt's latch; volatile so it cannot be folded away */

void pl_emit(int c)
{
    out_ring[ring_head & (sizeof out_ring - 1)] = (u8)c;
    ring_head++;
}

/* -1 = "no key pressed"; the engine pushes it as a cell, exactly like an empty caller. */
int pl_key(void)
{
    return -1;
}

/* op codes as documented in uforth.c: 0 gpio_get 1 gpio_set 2 adc 3 ms 4 wake 5 key? */
u32 pl_hw(int op, u32 a, u32 b)
{
    switch (op) {
    case 0: return mailbox[a & 53];                 /* gpio_get: the mailbox is the status store */
    case 1: mailbox[a & 53] = b; return 0;          /* gpio_set */
    case 2: return mailbox[a & 53] >> 4;            /* adc */
    case 3: ring_head += a; return 0;               /* ms: ticks */
    /* P33: op 6 is the block doorbell. It must make a real store, or the call is dead code and
     * BLKXFER's cost leaves the image with it (P22's 192 B lesson). */
    case 6: out_ring[ring_head & (sizeof out_ring - 1)] = (u8)'B'; ring_head++; return 0;
    default: return 0;                              /* wake, key? */
    }
}

/* P29's fourth hook: the layer stops the machine when the last task retires. Real, not a stub —
 * it latches a status the outer loop tests, and touches the ring so its bytes are the layer's. */
void pl_halt(int code)
{
    halt_status = (u32)code + 1u;
    out_ring[ring_head & (sizeof out_ring - 1)] = (u8)'H';
    ring_head++;
}

int main(void)
{
    static const char seed[] = "12 34 +";
    u8 i;

    for (i = 0; seed[i] && i < TIBSZ - 1; i++) tib[i] = (u8)seed[i];
    tl = i; ti = 0;

#ifndef P29_HARNESS_ONLY
    /* Keeps the outer interpreter (word/find/number), the paging path and the switch alive under
     * --gc-sections. GUARDRAIL: interpret() is static, so GCC inlines the whole engine into main and
     * subtracting "the stub" by symbol stops working — the control image (-DP29_HARNESS_ONLY) is the
     * only honest way to subtract the harness. */
    interpret();
    vm_task_init(0, rd16(V_XLIT));
    vm_run_tasks();
#endif
    /* GUARDRAIL: every array on the 4.3 budget lines is touched through a volatile here. A plain
     * store to a static array whose address never escapes is dead-store-eliminated together with
     * the array, and P22's first "successful" link reported a fit that was 728 B of budget lines
     * short for exactly that reason. A missing symbol in nm -S means the link is a lie. */
    *(volatile u8 *)&cmd_ring[0]        = (u8)ring_head;
    *(volatile u8 *)&mailbox[0]         = (u8)ring_head;
    /* GUARDRAIL: out_ring must be READ here, not merely written by pl_emit — with the frames gone,
     * the removed `frm` touch was the only reader of the ring, so GCC dead-stored pl_emit's store
     * and dropped the whole 256 B line (P22's 192 B lesson, this time in the other direction: a
     * budget line can vanish when the code that *reads* it is what the probe removed). */
    *(volatile u8 *)&out_ring[0]        = out_ring[ring_head & (sizeof out_ring - 1)];
    /* GUARDRAIL: frm/ptab/ptab_lru_reserve do not exist under -DP33_NOPAGE — a touch list that
     * names a removed array is a link error, and a touch list that drops a remaining one is the
     * 728 B understatement P22 already paid for. mem[] carries the 512 B block buffer instead. */
#if !defined(P33_NOPAGE)
    *(volatile u8 *)&ptab[0]            = (u8)ring_head;
    *(volatile u8 *)&ptab_lru_reserve[0]= (u8)ring_head;
    *(volatile u8 *)&frm[0][0]          = out_ring[ring_head & (sizeof out_ring - 1)];
#endif
#if defined(P33_BLOCK)
    *(volatile u8 *)&mem[BLKADR]        = (u8)ring_head;   /* the block buffer is a budget line */
#endif
    *(volatile u8 *)&ds[0]              = (u8)sp;
    *(volatile u8 *)&rs[0]              = (u8)rsp;
    *(volatile u8 *)&tsk[0]             = (u8)cur;
    *(volatile u8 *)&tib[0]             = (u8)halt_status;
    return ring_head ? 0 : 0;
}
