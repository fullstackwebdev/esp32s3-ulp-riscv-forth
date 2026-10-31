/* P05 — HP-side driver for the ULP-RISC-V cycle/clock calibration.
 *
 * Runs the ULP kernel (main/ulp/main.S) at several wake periods, waits a fixed
 * window, stops the timer and prints every raw counter so the numbers can be
 * recomputed from the log alone.
 */
#include <stdio.h>
#include <string.h>
#include <inttypes.h>

#include "esp_timer.h"
#include "esp_rom_sys.h"
#include "esp_sleep.h"
#include "ulp_riscv.h"
#include "ulp_main.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

extern const uint8_t ulp_main_bin_start[] asm("_binary_ulp_main_bin_start");
extern const uint8_t ulp_main_bin_end[] asm("_binary_ulp_main_bin_end");

/* The generated ulp_main.h binds these to absolute RTC-slow-memory addresses,
   so read them through volatile pointers: a plain read may be hoisted out of
   the polling loop by the optimiser.
   GUARDRAIL: ulp_* symbols are linker-PROVIDEd absolute addresses, not variables with storage in
   .data — reading them non-volatile lets the optimiser cache the first value and every snapshot
   would report the counters of a stale wake; always cast through volatile. */
static inline uint32_t rd(const uint32_t *p) { return *(volatile const uint32_t *)p; }

typedef struct {
    uint32_t wake, cyc_top, cyc_end, gap, span_wake, top_min, top_max;
    uint32_t a1, a2, l1, l2, b1, b2, tick_gap;
    uint32_t t64, dt64, t256, dt256, t1024, dt1024;
} raw_t;

static raw_t read_raw(void)
{
    raw_t r;
    r.wake      = rd(&ulp_wake_ctr);
    r.cyc_top   = rd(&ulp_cyc_top);
    r.cyc_end   = rd(&ulp_cyc_end);
    r.gap       = rd(&ulp_gap);
    r.span_wake = rd(&ulp_span_wake);
    r.top_min   = rd(&ulp_top_min);
    r.top_max   = rd(&ulp_top_max);
    r.a1        = rd(&ulp_span_a1);
    r.a2        = rd(&ulp_span_a2);
    r.l1        = rd(&ulp_span_l1);
    r.l2        = rd(&ulp_span_l2);
    r.b1        = rd(&ulp_span_b1);
    r.b2        = rd(&ulp_span_b2);
    r.t64       = rd(&ulp_span_t64);
    r.dt64      = rd(&ulp_dt_t64);
    r.t256      = rd(&ulp_span_t256);
    r.dt256     = rd(&ulp_dt_t256);
    r.t1024     = rd(&ulp_span_t1024);
    r.dt1024    = rd(&ulp_dt_t1024);
    r.tick_gap  = rd(&ulp_tick_gap);
    return r;
}

/* cycles per body op from the 10-vs-30 differential: 20 extra ops x 100 iters */
static void report_block(const char *name, uint32_t span10, uint32_t span30)
{
    int32_t d = (int32_t)span30 - (int32_t)span10;
    /* fixed-point x1000 so the log carries milli-cycles */
    int32_t milli = (int32_t)(((int64_t)d * 1000) / 2000);
    printf("BLOCK %s span10=%" PRIu32 " span30=%" PRIu32 " delta=%" PRId32
           " milli_cycles_per_op=%" PRId32 "\n", name, span10, span30, d, milli);
}

/* cycles per tick for one K block; milli-cycles fixed point, 0 if not measured */
static int32_t milli_cycles_per_tick(uint32_t span, uint32_t dt)
{
    if (dt == 0) {
        return 0;
    }
    return (int32_t)(((int64_t)span * 1000) / (int64_t)dt);
}

static void report_ticks(const char *tag, const raw_t *r)
{
    int32_t c64   = milli_cycles_per_tick(r->t64, r->dt64);
    int32_t c256  = milli_cycles_per_tick(r->t256, r->dt256);
    int32_t c1024 = milli_cycles_per_tick(r->t1024, r->dt1024);
    printf("TICK %s span64=%" PRIu32 " dt64=%" PRIu32 " mcyc64=%" PRId32
           " span256=%" PRIu32 " dt256=%" PRIu32 " mcyc256=%" PRId32
           " span1024=%" PRIu32 " dt1024=%" PRIu32 " mcyc1024=%" PRId32 "\n",
           tag, r->t64, r->dt64, c64, r->t256, r->dt256, c256, r->t1024, r->dt1024, c1024);
    /* core frequency = cycles_per_tick x slow-clock frequency */
    if (r->tick_gap > 0 && r->wake > 1) {
        printf("CORE %s mcyc1024=%" PRId32 " tick_gap=%" PRIu32 "\n", tag, c1024, r->tick_gap);
    }
}

static void run_phase(uint32_t period_us, uint32_t window_ms, const char *tag)
{
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(20));

    /* reload => RTC slow memory is cleared and re-initialised from the image */
    ESP_ERROR_CHECK(ulp_riscv_load_binary(ulp_main_bin_start,
                                         (size_t)(ulp_main_bin_end - ulp_main_bin_start)));
    ulp_top_min = 0xFFFFFFFFu;
    ulp_top_max = 0;
    ulp_cyc_end_prev = 0;
    ulp_tick_low_prev = 0;
    __sync_synchronize();

    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, period_us));
    ESP_ERROR_CHECK(ulp_riscv_run());

    int64_t t_start = esp_timer_get_time();
    /* bounded twice: wall-clock window and an iteration cap */
    for (int i = 0; i < (int)(window_ms * 4); i++) {
        // GUARDRAIL: pdMS_TO_TICKS(1) is 0 at the IDF default CONFIG_FREERTOS_HZ=100, so
        // vTaskDelay(0) only yields and this "window" collapsed to its 60 ms iteration cap on
        // every phase — that is why the wall-clock cross-check is missing from this result.
        // Use esp_rom_delay_us(1000) or raise CONFIG_FREERTOS_HZ for a real millisecond window.
        esp_rom_delay_us(1000);
        if (esp_timer_get_time() - t_start >= (int64_t)window_ms * 1000) {
            break;
        }
    }
    int64_t elapsed = esp_timer_get_time() - t_start;

    /* stop future wakes; the wake in flight completes, then the counters are stable */
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(50));
    raw_t r = read_raw();

    int64_t interval_us_milli = 0;
    if (r.wake > 1) {
        interval_us_milli = (elapsed * 1000) / (int64_t)r.wake;
    }
    printf("PHASE %s period_us=%" PRIu32 " window_us=%" PRId64 " wakes=%" PRIu32
           " interval_us_milli=%" PRId64 " tick_gap=%" PRIu32 "\n",
           tag, period_us, elapsed, r.wake, interval_us_milli, r.tick_gap);
    printf("RAW %s wake=%" PRIu32 " cyc_top=%" PRIu32 " cyc_end=%" PRIu32
           " gap=%" PRIu32 " span_wake=%" PRIu32 " top_min=%" PRIu32 " top_max=%" PRIu32
           " a1=%" PRIu32 " a2=%" PRIu32 " l1=%" PRIu32 " l2=%" PRIu32
           " b1=%" PRIu32 " b2=%" PRIu32 "\n",
           tag, r.wake, r.cyc_top, r.cyc_end, r.gap, r.span_wake, r.top_min, r.top_max,
           r.a1, r.a2, r.l1, r.l2, r.b1, r.b2);
    report_block("addi",  r.a1, r.a2);
    report_block("lw",    r.l1, r.l2);
    report_block("lb",    r.b1, r.b2);
    report_ticks(tag, &r);
    if (r.tick_gap > 0 && interval_us_milli > 0) {
        /* tick_gap ticks per wake over interval_us_milli/1000 us => Hz = ticks * 1e9/us.
         * tick_gap is read by the ULP through the TIME_UPDATE latch, so this is the
         * only wall-clock cross-check that does not come from esp_timer alone. */
        int64_t hz_milli = ((int64_t)r.tick_gap * 1000000000LL) / interval_us_milli;
        printf("SLOWCLK %s tick_gap=%" PRIu32 " interval_us_milli=%" PRId64
               " hz_milli=%" PRId64 "\n", tag, r.tick_gap, interval_us_milli, hz_milli);
    }
}

void app_main(void)
{
    /* USB-serial-jtag needs time to reconnect after a reset before printf lands */
    vTaskDelay(pdMS_TO_TICKS(1500));

    printf("P05 start (CONFIG_ULP_COPROC_RESERVE_MEM=%d)\n", CONFIG_ULP_COPROC_RESERVE_MEM);

    run_phase(73535, 2000, "p10000t");   /* nominally 10000 ticks at 136 kHz */
    run_phase(735,     1000, "p100t_a");
    run_phase(735,     1000, "p100t_b");
    run_phase(735,     1000, "p100t_c");
    run_phase(74,      600,  "p10t");
    run_phase(8,       600,  "p1t");

    ulp_riscv_timer_stop();
    printf("P05 done\n");
}
