/*
 * P06 — ULP-RISC-V wake-semantics kernel.
 *
 * One wake = one pass.  Every pass:
 *   - stamps rdcycle at main entry (constant 81 = the wake overhead P05 measured),
 *   - latches the RTC counter at wake start (t0) and at wake end (t1), so the
 *     wake's own duration is measurable in ticks,
 *   - computes gap = t0 - t0_prev (interval between consecutive wake *starts*)
 *     and resid = gap - span_prev (slack left after the previous wake ended),
 *   - busy-waits `delay_cycles` cycles bounded by rdcycle, then returns.
 *
 * mode == 0 : normal pass, returns into __start -> ulp_riscv_halt().
 * mode == 1 : aborted pass, sets COCPU_DONE|COCPU_SHUT_RESET_EN itself and
 *             spins — the non-return path.  Used to prove DONE is set there too.
 */

    .section .text
    .global main
    .type main, %function

/* RTC_CNTL offsets inside the ULP's RTCCNTL window base 0x8000 (esp32s3.peripherals.ld).
 * GUARDRAIL: the ULP sees the RTC block at 0x8000-based offsets, not the HP 0x6008_xxxx
 * aliases — using the HP alias from the ULP silently reads RTC slow RAM and yields fake
 * register values (P05 lost its whole cycles-per-tick result to this class of bug). */
    .equ RTCCNTL,             0x8000
    .equ RTC_TIME_UPDATE,     0x0c   /* WO; request bit is BIT(31), not bit 0 */
    .equ RTC_TIME_LOW0,       0x10   /* RO; latched snapshot */
    .equ RTC_COCPU_CTRL,      0x104
    .equ COCPU_DONE,          (1 << 25)
    .equ COCPU_SHUT_RESET_EN, (1 << 22)
    /* RTC_CNTL_SLP_WAKEUP_CAUSE_REG (rtc_cntl_reg.h:3217), field WAKEUP_CAUSE[16:0].
     * GUARDRAIL: the wake cause must be read from this register, not inferred from the
     * wake counter — the counter cannot distinguish a timer wake from a GPIO wake, and
     * the whole coexistence question is whether the two are attributable. */
    .equ RTC_SLP_WAKEUP_CAUSE, 0x130
    .equ WAKEUP_CAUSE_MASK,   0x1FFFF

/* TICK_READ rd — latch a fresh RTC timer snapshot then read its low word.
 * s6 must already hold RTCCNTL.  Clobbers t2.
 * GUARDRAIL: RTC_CNTL_TIME_LOW0 is a latched snapshot that only refreshes when the
 * TIME_UPDATE BIT(31) is written; a bare read returns the boot-time value forever, so
 * every "tick gap" of 0 is a missing latch, not a missing counter. */
.macro TICK_READ rd
    li   t2, 0x80000000
    sw   t2, RTC_TIME_UPDATE(s6)
1:  lw   t2, RTC_TIME_UPDATE(s6)
    bltz t2, 1b
    lw   \rd, RTC_TIME_LOW0(s6)
.endm

main:
    rdcycle s1
    la t0, cyc_top
    sw s1, 0(t0)

    li s6, RTCCNTL
    TICK_READ s10                 /* t0 of this wake */
    mv s7, s10

    /* Per-wake wake-source stamp: the raw cause register plus the tick at which the
     * wake started.  The HP side pair-compares (cause, tick) against the timer-only
     * baseline to attribute each wake and to time a GPIO edge to its wake. */
    la t0, wake_tick_last
    sw s10, 0(t0)
    lw t2, RTC_SLP_WAKEUP_CAUSE(s6)
    li t3, WAKEUP_CAUSE_MASK
    and t2, t2, t3
    la t0, cause_last
    sw t2, 0(t0)

    /* First pass after ulp_riscv_load_binary has tick_start_prev cleared: skip the
     * delta statistics, they would be pure garbage (t0 - 0). */
    la t0, tick_start_prev
    lw t2, 0(t0)
    beqz t2, no_stats

    sub s2, s7, t2                /* gap between consecutive wake starts */
    la t0, gap_last
    sw s2, 0(t0)
    /* GUARDRAIL: P05's min/max tracker never stored because its bgeu branch was inverted;
     * write it as "if (new < min) store" with bltu against the loaded value. */
    la t0, gap_min
    lw t3, 0(t0)
    bgeu t3, s2, 1f
    sw s2, 0(t0)
1:  la t0, gap_max
    lw t3, 0(t0)
    bgeu s2, t3, 2f
    sw s2, 0(t0)
2:  la t0, gap_sum
    lw t3, 0(t0)
    add t3, t3, s2
    sw t3, 0(t0)

    /* resid = gap this wake - duration of the previous wake.  This is THE overrun
     * discriminator, in integer ticks: resid ~= period  => the tick was lost and the
     * timer waited for the next period boundary; resid ~= 0 => the pending tick was
     * latched and fired the instant the previous wake retired. */
    la t0, span_prev
    lw t3, 0(t0)
    sub s3, s2, t3
    la t0, resid_last
    sw s3, 0(t0)
    la t0, resid_min
    lw t4, 0(t0)
    bgeu t4, s3, 3f
    sw s3, 0(t0)
3:  la t0, resid_max
    lw t4, 0(t0)
    bgeu s3, t4, 4f
    sw s3, 0(t0)
4:  la t0, resid_sum
    lw t4, 0(t0)
    add t4, t4, s3
    sw t4, 0(t0)
    la t0, stat_ctr
    lw t4, 0(t0)
    addi t4, t4, 1
    sw t4, 0(t0)

no_stats:
    la t0, tick_start_prev
    sw s10, 0(t0)

    /* ---- abort path: prove DONE is set on a non-return exit ---- */
    la t0, mode
    lw t2, 0(t0)
    beqz t2, normal

    la t0, abort_ctr
    lw t2, 0(t0)
    addi t2, t2, 1
    sw t2, 0(t0)
    li t2, (COCPU_DONE | COCPU_SHUT_RESET_EN)
    sw t2, RTC_COCPU_CTRL(s6)
5:  j 5b

normal:
    /* ---- rdcycle-bounded busy wait: the genuine overrun, no yielding opcode ---- */
    la t0, delay_cycles
    lw s8, 0(t0)
    rdcycle s2
    add s8, s8, s2
6:  rdcycle s9
    bltu s9, s8, 6b

    rdcycle s1
    la t0, cyc_end
    sw s1, 0(t0)

    TICK_READ s7                  /* t1 of this wake */
    la t0, tick_end
    sw s7, 0(t0)
    sub s3, s7, s10               /* span of this wake, in ticks */
    la t0, span_last
    sw s3, 0(t0)
    la t0, span_prev
    sw s3, 0(t0)
    la t0, span_min
    lw t4, 0(t0)
    bgeu t4, s3, 7f
    sw s3, 0(t0)
7:  la t0, span_max
    lw t4, 0(t0)
    bgeu s3, t4, 8f
    sw s3, 0(t0)
8:  la t0, span_sum
    lw t4, 0(t0)
    add t4, t4, s3
    sw t4, 0(t0)

    la t0, wake_ctr
    lw t2, 0(t0)
    addi t2, t2, 1
    sw t2, 0(t0)
    la t0, done
    lw t2, 0(t0)
    addi t2, t2, 1
    sw t2, 0(t0)
    ret

    .size main, .-main

    .section .bss
    .balign 4
    .global wake_ctr
    .global done
    .global abort_ctr
    .global mode
    .global delay_cycles
    .global cyc_top
    .global cyc_end
    .global tick_start_prev
    .global tick_end
    .global gap_last
    .global gap_min
    .global gap_max
    .global gap_sum
    .global span_last
    .global span_prev
    .global span_min
    .global span_max
    .global span_sum
    .global resid_last
    .global resid_min
    .global resid_max
    .global resid_sum
    .global cause_last
    .global wake_tick_last
    .global stat_ctr
wake_ctr:        .space 4
done:            .space 4
abort_ctr:       .space 4
mode:            .space 4
delay_cycles:    .space 4
cyc_top:         .space 4
cyc_end:         .space 4
tick_start_prev: .space 4
tick_end:        .space 4
gap_last:        .space 4
gap_min:         .space 4
gap_max:         .space 4
gap_sum:         .space 4
span_last:       .space 4
span_prev:       .space 4
span_min:        .space 4
span_max:        .space 4
span_sum:        .space 4
resid_last:      .space 4
resid_min:       .space 4
resid_max:       .space 4
resid_sum:       .space 4
cause_last:      .space 4
wake_tick_last:  .space 4
stat_ctr:        .space 4
