/* ulp_main.c - ULP-RISC-V LoRa transmit node for the Heltec V3 (ESP32-S3 + SX1262)
 *
 * Each timer wake: measure the SPI bus, bring the radio up (or reuse a warm configuration), send one 20-byte packet,
 * put the radio back to sleep, halt. The main core never wakes for this; it only reads the counters below.
 */
#include <stdint.h>

#include "ulp_riscv_utils.h"
#include "sx126x_ulp_hal.h"
#include "sx126x_min.h"

/* ---- Exported to the main CPU as ulp_<name> ---- */
volatile uint32_t run_count;              /* timer wakes since start                        */
volatile uint32_t tx_ok_count;
volatile uint32_t tx_fail_count;
volatile int32_t  last_error;             /* 0 = ok, else HAL/driver error                  */
volatile uint32_t radio_ready;            /* 1 = warm configuration believed valid          */
volatile uint32_t cfg_used;               /* 0 = tried no TCXO, 1 = TCXO needed             */
volatile uint32_t spi_cycles_per_byte;    /* measured, 0 = not measured yet                 */
volatile uint32_t status_byte;            /* GetStatus reply from the chip, 0 = none        */
volatile uint32_t pad_selftest;           /* 0 = every driven pad followed; else see hal_pad_selftest */
volatile uint32_t tx_cycles;              /* SET_TX -> TxDone, in 17.5 MHz cycles: the measured air time */
volatile uint32_t buf_verify;             /* 0 = the radio's TX buffer matched what we wrote */
volatile uint32_t ccount_cal;             /* cycles measured across a known 10 ms delay: calibrates the counter */
volatile uint32_t awake;
/* GUARDRAIL: exported for the cross-firmware probe. The Forth firmware's ULP reads RTCIO as 0x1C008000 while its HP core
 * reads 0x00400000, and writes land nowhere - the same three lines added HERE answer whether that is this board's
 * behaviour or that firmware's: if probe_out comes back with bit 18 set, the probe logic is sound and the fault is
 * environmental to the other image. */
volatile uint32_t probe_out;
volatile uint32_t probe_sens;                  /* 1 while the ULP is running: the main core times this window */
volatile uint32_t cold_count;             /* cold inits performed: if this tracks run_count, warm start is NOT working */

/* Heltec V3: the SX1262's TCXO is powered from DIO3 at 1.8 V, and DIO2 drives the antenna switch. Both are facts about
 * this module that the bring-up *proves* rather than assumes: cfg A is tried without the TCXO and cfg B with it, and
 * whichever produces TxDone is recorded in cfg_used (docs/14 R16 - a plausible status is not an identity). */
#define TCXO_VOLTAGE_1V8 0x02

static const sx126x_cfg_t cfg_a = {
    .rf_freq_reg    = SX126X_FREQ_REG(868100000UL),
    .img_cal        = SX126X_IMGCAL_863_870,
    .sf             = 9,
    .bw             = SX126X_BW_125,
    .cr             = 1,
    .ldro           = 0,
    .tx_dbm         = 14,
    .preamble       = 8,
    .use_dcdc       = 1,
    .use_tcxo       = 0,
    .tcxo_voltage   = 0,
    .dio2_rf_switch = 1,
};

static const sx126x_cfg_t cfg_b = {
    .rf_freq_reg    = SX126X_FREQ_REG(868100000UL),
    .img_cal        = SX126X_IMGCAL_863_870,
    .sf             = 9,
    .bw             = SX126X_BW_125,
    .cr             = 1,
    .ldro           = 0,
    .tx_dbm         = 14,
    .preamble       = 8,
    .use_dcdc       = 1,
    .use_tcxo       = 1,
    .tcxo_voltage   = TCXO_VOLTAGE_1V8,
    .dio2_rf_switch = 1,
};

int main(void)
{
    uint8_t pkt[20];
    uint8_t st = 0;
    uint32_t v;
    int e;

    run_count++;
    awake = 1;

    /* GUARDRAIL: the cross-firmware probe, three lines, identical to the one in probe/repl's ULP. Here it is known-good
     * (this image transmits), so its answer separates "the board cannot do this" from "that image cannot". */
    *(volatile uint32_t *)0x60008404u = (1u << 18);        /* RTC_GPIO_OUT_W1TS: set pad 8 (NSS) */
    probe_out = *(volatile uint32_t *)0x60008400u;         /* read OUT back            */
    probe_sens = *(volatile uint32_t *)0x60008904u;        /* read SENS clk gate       */

#if !defined(LORA_NOINIT)
    hal_init();          /* F-171: this is the call being bisected - the cut below deletes it and nothing else */
#endif
#if defined(LORA_NOINIT)
    /* GUARDRAIL: F-171's second cut. Cut #1 (radio work deleted, hal_init kept) LANDED, so the 195 ms of SPI was never
     * the reason and the reason is inside hal_init(). This cut removes hal_init() and nothing else: if the store still
     * lands, hal_init is not the gate and the remaining difference is in how the two images are built/loaded; if it goes
     * LOST, hal_init's pad configuration opens the path - and the next bisect is which of its lines does it, which is
     * the answer the Forth driver needs. */
    {
        volatile uint32_t keep2;
        keep2 = run_count;
        (void)keep2;
    }
#endif

#if defined(LORA_MIN)
    /* GUARDRAIL: F-170, the INVERSE bisect. Every previous probe walked from this firmware's broken side toward the
     * reference and nothing flipped, so start from the artifact that LANDS and delete toward ours: this cut keeps the
     * wake entry and the pad enables and returns before ANY radio work - no SPI, no 195 ms bit-bang, no cold init, no
     * self-tests. Two answers and both are decisive:
     *   LOST  -> a lone store followed by halt never reaches the APB; this image lands only because its wake goes on to
     *            do milliseconds of further peripheral traffic. The Forth driver writes in bursts anyway, so that
     *            reopens the board test of LORA_INIT/LORA_SEND immediately.
     *   LANDS -> landing is a property of the image, not of the work, so the next cut changes this build's LINK flags
     *            (the gc-sections/-msave-restore/-fno-tree-* set) until it flips.
     * The witness is the HP core clearing pad 8 and reading it back (tests/staytest.py), keyed to the wake - never this
     * core's own register reads, which are garbage in both firmwares (F-158). */
    /* GUARDRAIL: keep every exported variable referenced. --gc-sections drops the now-unreachable radio and counter
     * variables, the IDF map generator stops exporting them, and the HP side fails with
     * "'ulp_tx_ok_count' undeclared" - which reads like a CMake/linker mystery and is just the linker doing its job
     * (same lesson as probe/repl/src/ulp_stub.c and the P42 bench main). The cuts must LOOK like they use what they
     * define, so that the two builds being compared differ only in the work being cut. */
    {
        volatile uint32_t keep;
        keep = radio_ready; keep = cfg_used; keep = tx_ok_count; keep = tx_fail_count;
        keep = last_error; keep = status_byte; keep = tx_cycles; keep = buf_verify;
        keep = spi_cycles_per_byte; keep = pad_selftest; keep = ccount_cal;
        keep = cold_count; keep = awake; keep = probe_out; keep = probe_sens;
        (void)keep;
    }
    return 0;
#endif

    if (ccount_cal == 0) {
        /* GUARDRAIL: calibrate before believing any cycle-based duration. ULPs' cycle counter is a 32-bit free-running
         * value and a plain end-start across a long gap silently wraps; measuring it against a KNOWN delay turns that
         * from a wrong number into a visible one (17.5 MHz * 10 ms = 175 000). */
        uint32_t c0 = (uint32_t)ULP_RISCV_GET_CCOUNT();
        hal_delay_ms(10);
        ccount_cal = (uint32_t)ULP_RISCV_GET_CCOUNT() - c0;
    }

    if (pad_selftest == 0) {
        pad_selftest = hal_pad_selftest() + 1u;   /* +1 so "ran and clean" is distinguishable from "not run" */
    }

    if (spi_cycles_per_byte == 0) {
        spi_cycles_per_byte = hal_bench_cycles_per_byte(16);
    }

    /* 20-byte payload: marker, run counter, and a fixed pattern that is recognisable on air. */
    pkt[0] = 0xA5;
    v = run_count;
    pkt[1] = (uint8_t)(v >> 24); pkt[2] = (uint8_t)(v >> 16);
    pkt[3] = (uint8_t)(v >> 8);  pkt[4] = (uint8_t)v;
    for (int i = 5; i < 20; i++) {
        pkt[i] = (uint8_t)(0x30 + i);
    }

    /* First attempt: whatever we believe works. On a cold start that is cfg A, so the TCXO question gets answered. */
    e = radio_ready ? sx126x_send(&cfg_b, pkt, sizeof pkt, 3000, &tx_cycles) : -100;

    if (e != 0) {
        /* Cold init, in the order that answers the hardware question: no TCXO first, then TCXO. */
        cold_count++;
        e = sx126x_cold_init(&cfg_a);
        if (e == 0) {
            e = sx126x_send(&cfg_a, pkt, sizeof pkt, 3000, &tx_cycles);
            cfg_used = 0;
        }
        if (e != 0) {
            cold_count++;
            e = sx126x_cold_init(&cfg_b);
            if (e == 0) {
                e = sx126x_send(&cfg_b, pkt, sizeof pkt, 3000, &tx_cycles);
                cfg_used = 1;
            }
        }
        if (e == 0) {
            radio_ready = 1;
            (void)sx126x_status(&st);
            status_byte = st;
        } else {
            radio_ready = 0;
            (void)sx126x_status(&st);
            status_byte = st;
        }
    }

    /* Read the payload back out of the radio: TxDone says the modem ran, this says it ran on OUR bytes. */
    buf_verify = (uint32_t)sx126x_verify_buffer(pkt, sizeof pkt);

    (void)sx126x_sleep(1);

    if (e == 0) {
        tx_ok_count++;
    } else {
        tx_fail_count++;
        radio_ready = 0;
    }
    last_error = e;
    awake = 0;

    ulp_riscv_halt();
    return 0;
}
