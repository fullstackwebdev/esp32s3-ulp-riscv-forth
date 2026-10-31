/*
 * P05 — cycle / clock calibration kernels for the ESP32-S3 ULP-RISC-V core.
 *
 * One wake = one pass: stamp cycles, run four differential measurement blocks,
 * read the RTC timer counter around a long dependent chain, then return to
 * __start which calls ulp_riscv_halt().  Nothing spins: main always returns.
 *
 * Every block is measured twice with the *same* loop overhead and a different
 * body length (10 vs 30 body instructions, 100 iterations).  The difference
 * between the two spans is exactly 2000 body instructions, so
 *   cycles_per_<op> = (span_30 - span_10) / (20 * ITER)
 * with all setup, loop-counter and branch costs cancelling.
 */

    .section .text
    .global main
    .type main, %function

/* RTC_CNTL register offsets relative to the ULP's RTCCNTL window base 0x8000
 * (components/ulp/ld/esp32s3.peripherals.ld; the HP aliases are 0x6008_xxxx).
 * GUARDRAIL: the ULP's peripheral window is the low 64 KB, not the HP 0x6000_xxxx
 * aliases — reading 0x6008_0010 from the ULP reads RTC slow memory and silently
 * produces a fake "tick" — always use the 0x8000-based offsets here. */
    .equ RTCCNTL, 0x8000
    .equ RTC_TIME_UPDATE, 0x0c  /* WO, request bit is BIT(31) — not bit 0 */
    .equ RTC_TIME_LOW0, 0x10    /* RO, latched snapshot */

    .equ ITER, 100          /* iterations per differential block */

/* TICK_READ rd — latch a fresh RTC timer snapshot into TIME_LOW0/HIGH0 and read
 * the low word into \rd.  s6 must already hold RTCCNTL (0x8000).
 * GUARDRAIL: RTC_CNTL_TIME_LOW0 is a *latched* snapshot that only refreshes when
 * the TIME_UPDATE bit is written; reading it bare returns the value latched at
 * boot forever (first P05 run measured tick0 == tick1 == 416095043 and lost the
 * whole cycles-per-tick result).  Also the request bit is BIT(31), not bit 0:
 * writing 1 to the register sets a different (harmless) field and the latch never
 * happens.  Write 0x80000000, poll until bit 31 self-clears, then read. */
.macro TICK_READ rd
    li   t2, 0x80000000
    sw   t2, RTC_TIME_UPDATE(s6)
1:  lw   t2, RTC_TIME_UPDATE(s6)
    bltz t2, 1b                 /* bit 31 still set => snapshot not ready */
    lw   \rd, RTC_TIME_LOW0(s6)
.endm

main:
    /* Wake bookkeeping.  cyc_top is the first instruction of main, so it also
     * measures how many core cycles were burnt before main by reset_vector and
     * __start (if mcycle is reset per wake) — that is the wake overhead. */
    rdcycle s1
    la t0, cyc_top
    sw s1, 0(t0)
    la t0, cyc_end_prev
    lw t2, 0(t0)
    sub t2, s1, t2
    la t3, gap
    sw t2, 0(t3)
    la t0, top_min
    lw t2, 0(t0)
    bgeu t2, s1, 1f
    sw s1, 0(t0)
1:  la t0, top_max
    lw t2, 0(t0)
    bgeu s1, t2, 2f
    sw s1, 0(t0)
2:  la t0, wake_ctr
    lw t2, 0(t0)
    addi t2, t2, 1
    sw t2, 0(t0)

    /* Ticks elapsed since the previous wake, read from the same RTC counter.
     * GUARDRAIL: cyc_top/cyc_end alone cannot give cycles-per-tick — the core is
     * clock-gated between wakes, so the only wall clock the ULP can see is the
     * RTC counter.  Sample it every wake and let the HP side divide by the
     * esp_timer-measured interval.  Deltas within one wake are far below 2^32
     * ticks (8.7 h at 136 kHz), so the low word alone is sufficient here. */
    li s6, RTCCNTL
    TICK_READ s7
    la t3, tick_low_prev
    lw t2, 0(t3)
    sub t2, s7, t2
    la t3, tick_gap
    sw t2, 0(t3)
    la t3, tick_low_prev
    sw s7, 0(t3)

    /* ---- A1: dependent addi chain, 10 per iteration ---- */
    la s3, span_a1
    li s4, ITER
    li a0, 0
    rdcycle s2
3:  .rept 10
    addi a0, a0, 1
    .endr
    addi s4, s4, -1
    bnez s4, 3b
    rdcycle s5
    sub s5, s5, s2
    sw s5, 0(s3)

    /* ---- A2: same, 30 per iteration ---- */
    la s3, span_a2
    li s4, ITER
    li a0, 0
    rdcycle s2
4:  .rept 30
    addi a0, a0, 1
    .endr
    addi s4, s4, -1
    bnez s4, 4b
    rdcycle s5
    sub s5, s5, s2
    sw s5, 0(s3)

    /* ---- L1: 10 RTC-RAM word loads per iteration ---- */
    la s3, span_l1
    la a1, scratch
    li s4, ITER
    rdcycle s2
5:  lw a0, 0(a1)
    lw a0, 4(a1)
    lw a0, 8(a1)
    lw a0, 12(a1)
    lw a0, 16(a1)
    lw a0, 20(a1)
    lw a0, 24(a1)
    lw a0, 28(a1)
    lw a0, 32(a1)
    lw a0, 36(a1)
    addi s4, s4, -1
    bnez s4, 5b
    rdcycle s5
    sub s5, s5, s2
    sw s5, 0(s3)

    /* ---- L2: same, 30 loads per iteration ---- */
    la s3, span_l2
    la a1, scratch
    li s4, ITER
    rdcycle s2
6:  lw a0, 0(a1)
    lw a0, 4(a1)
    lw a0, 8(a1)
    lw a0, 12(a1)
    lw a0, 16(a1)
    lw a0, 20(a1)
    lw a0, 24(a1)
    lw a0, 28(a1)
    lw a0, 32(a1)
    lw a0, 36(a1)
    lw a0, 40(a1)
    lw a0, 44(a1)
    lw a0, 48(a1)
    lw a0, 52(a1)
    lw a0, 56(a1)
    lw a0, 60(a1)
    lw a0, 64(a1)
    lw a0, 68(a1)
    lw a0, 72(a1)
    lw a0, 76(a1)
    lw a0, 80(a1)
    lw a0, 84(a1)
    lw a0, 88(a1)
    lw a0, 92(a1)
    lw a0, 96(a1)
    lw a0, 100(a1)
    lw a0, 104(a1)
    lw a0, 108(a1)
    lw a0, 112(a1)
    lw a0, 116(a1)
    addi s4, s4, -1
    bnez s4, 6b
    rdcycle s5
    sub s5, s5, s2
    sw s5, 0(s3)

    /* ---- K: cycles per RTC_SLOW_CLK tick ----
     * t0 = rdcycle, then re-latch and poll the RTC counter until it has advanced
     * by at least K ticks, then t1 = rdcycle.  cycles_per_tick = (t1-t0)/delta,
     * where delta is the *observed* tick advance, not the requested K, so a
     * one-tick overshoot at the polling boundary cannot bias the result.
     * The poll body is 5 instructions (~40 cycles), i.e. the span is measured to
     * within one poll iteration; three K values quantise that error differently. */
    li s6, RTCCNTL

    /* ---- K1: 64 ticks ---- */
    la s3, span_t64
    TICK_READ s7
    rdcycle s2
    li s10, 64
7:  TICK_READ s8
    sub t1, s8, s7
    bltu t1, s10, 7b
    rdcycle s5
    sub s5, s5, s2
    sw s5, 0(s3)
    la t0, dt_t64
    sw t1, 0(t0)

    /* ---- K2: 256 ticks ---- */
    la s3, span_t256
    TICK_READ s7
    rdcycle s2
    li s10, 256
7:  TICK_READ s8
    sub t1, s8, s7
    bltu t1, s10, 7b
    rdcycle s5
    sub s5, s5, s2
    sw s5, 0(s3)
    la t0, dt_t256
    sw t1, 0(t0)

    /* ---- K3: 1024 ticks ---- */
    la s3, span_t1024
    TICK_READ s7
    rdcycle s2
    li s10, 1024
7:  TICK_READ s8
    sub t1, s8, s7
    bltu t1, s10, 7b
    rdcycle s5
    sub s5, s5, s2
    sw s5, 0(s3)
    la t0, dt_t1024
    sw t1, 0(t0)

    /* ---- B1: 10 byte loads per iteration (prototype rd8) ---- */
    la s3, span_b1
    la a1, scratch
    li s4, ITER
    rdcycle s2
8:  lb a0, 0(a1)
    lb a0, 1(a1)
    lb a0, 2(a1)
    lb a0, 3(a1)
    lb a0, 4(a1)
    lb a0, 5(a1)
    lb a0, 6(a1)
    lb a0, 7(a1)
    lb a0, 8(a1)
    lb a0, 9(a1)
    addi s4, s4, -1
    bnez s4, 8b
    rdcycle s5
    sub s5, s5, s2
    sw s5, 0(s3)

    /* ---- B2: same, 30 byte loads per iteration ---- */
    la s3, span_b2
    la a1, scratch
    li s4, ITER
    rdcycle s2
9:  lb a0, 0(a1)
    lb a0, 1(a1)
    lb a0, 2(a1)
    lb a0, 3(a1)
    lb a0, 4(a1)
    lb a0, 5(a1)
    lb a0, 6(a1)
    lb a0, 7(a1)
    lb a0, 8(a1)
    lb a0, 9(a1)
    lb a0, 10(a1)
    lb a0, 11(a1)
    lb a0, 12(a1)
    lb a0, 13(a1)
    lb a0, 14(a1)
    lb a0, 15(a1)
    lb a0, 16(a1)
    lb a0, 17(a1)
    lb a0, 18(a1)
    lb a0, 19(a1)
    lb a0, 20(a1)
    lb a0, 21(a1)
    lb a0, 22(a1)
    lb a0, 23(a1)
    lb a0, 24(a1)
    lb a0, 25(a1)
    lb a0, 26(a1)
    lb a0, 27(a1)
    lb a0, 28(a1)
    lb a0, 29(a1)
    addi s4, s4, -1
    bnez s4, 9b
    rdcycle s5
    sub s5, s5, s2
    sw s5, 0(s3)

    /* ---- retire ---- */
    rdcycle s1
    la t0, cyc_end
    sw s1, 0(t0)
    la t0, cyc_end_prev
    sw s1, 0(t0)
    la t0, span_wake
    la t1, cyc_top
    lw t1, 0(t1)
    sub s1, s1, t1
    sw s1, 0(t0)
    la t0, done
    lw t1, 0(t0)
    addi t1, t1, 1
    sw t1, 0(t0)
    ret

    .size main, .-main

    .section .bss
    .balign 4
    .global wake_ctr
    .global cyc_top
    .global cyc_end
    .global cyc_end_prev
    .global gap
    .global span_wake
    .global top_min
    .global top_max
    .global span_a1
    .global span_a2
    .global span_l1
    .global span_l2
    .global span_b1
    .global span_b2
    .global span_t64
    .global span_t256
    .global span_t1024
    .global dt_t64
    .global dt_t256
    .global dt_t1024
    .global tick_gap
    .global tick_low_prev
    .global done
    .global scratch
wake_ctr:       .space 4
cyc_top:        .space 4
cyc_end:        .space 4
cyc_end_prev:   .space 4
gap:            .space 4
span_wake:      .space 4
top_min:        .space 4
top_max:        .space 4
span_a1:        .space 4
span_a2:        .space 4
span_l1:        .space 4
span_l2:        .space 4
span_b1:        .space 4
span_b2:        .space 4
span_t64:       .space 4
span_t256:      .space 4
span_t1024:     .space 4
dt_t64:         .space 4
dt_t256:        .space 4
dt_t1024:       .space 4
tick_gap:       .space 4
tick_low_prev:  .space 4
done:           .space 4
scratch:        .space 256
