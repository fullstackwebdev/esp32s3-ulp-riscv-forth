/* P18 — do RTC-IO pin latches survive a ULP sleep, and how many edges coalesce?
 *
 * The ULP is armed on the RTC timer ONLY (1000 ticks ~ 6.46 ms, no GPIO wakeup).  This core
 * drives GPIO4 with known edge counts / rates / pulse widths while the ULP is between wakes,
 * and the ULP reports, per wake, whether the RTC-IO interrupt status bit for GPIO4 was still
 * set.  Five things get numbers: N edges -> m events, the edge rate at which events stop
 * matching edges, the minimum pulse width the RTC domain can see, edge -> wake latency, and
 * whether the ULP's clear leaves the latch clean.
 *
 * Staged so a wedge is attributable: watchdog first, then UART, then banner, then 'g'.
 */
#include <stdio.h>
#include <string.h>
#include <inttypes.h>

#include "esp_timer.h"
#include "esp_rom_sys.h"
#include "esp_cpu.h"
#include "esp_attr.h"
#include "esp_system.h"
#include "esp_task_wdt.h"
#include "driver/uart.h"
#include "driver/gpio.h"
#include "driver/rtc_io.h"
#include "soc/soc.h"
#include "soc/rtc_io_reg.h"
#include "ulp_riscv.h"
#include "ulp_main.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

extern const uint8_t ulp_main_bin_start[] asm("_binary_ulp_main_bin_start");
extern const uint8_t ulp_main_bin_end[] asm("_binary_ulp_main_bin_end");

/* GUARDRAIL: ulp_* are linker-PROVIDEd absolute RTC-slow-memory addresses; read them through
 * a volatile pointer or the optimiser keeps a stale snapshot and a whole phase reports the
 * previous wake's counters (P05). */
static inline uint32_t rd(const uint32_t *p) { return *(volatile const uint32_t *)p; }
static inline void wr(uint32_t *p, uint32_t v) { *(volatile uint32_t *)p = v; __sync_synchronize(); }

/* GUARDRAIL: RTCIO data/status bits start at bit 10 (RTC GPIO0 = bit 10) — GPIO4 is bit 14.
 * BIT(4) clears nothing at all, which reads as "the latch never cleared". */
#define RTCIO_GPIO4_BIT  (1u << (10 + 4))

#define ULP_PERIOD_US    6460u          /* 1000 RTC ticks x 6.46 us (P05) */
#define WAKE_TMO_US      500000         /* 500 ms: 77 periods, so a stalled ULP is named */
#define RING             64u
#define PIN              GPIO_NUM_4     /* GPIO4: not USB(19/20), not strapping, not UART0 */

/* 0 = pad in the RTCIO mux and driven from RTCIO OUT_W1TS/W1TC, 1 = digital GPIO out.
 * Which one the RTC-IO edge detector can actually see is measured, not assumed (P16's open
 * follow-up: an RTC-IO write the HP never saw as a level). */
static int s_digital_drive;
static int s_level;                     /* last level this core drove on the pin */
static uint32_t s_lat[32];
static uint32_t s_nlat;

static inline void edge_high(void)
{
    if (s_digital_drive) {
        gpio_set_level(PIN, 1);
    } else {
        REG_WRITE(RTC_GPIO_OUT_W1TS_REG, RTCIO_GPIO4_BIT);
    }
    s_level = 1;
}

static inline void edge_low(void)
{
    if (s_digital_drive) {
        gpio_set_level(PIN, 0);
    } else {
        REG_WRITE(RTC_GPIO_OUT_W1TC_REG, RTCIO_GPIO4_BIT);
    }
    s_level = 0;
}

static uint32_t latch_bit(void)
{
    return (REG_READ(RTC_GPIO_STATUS_REG) & RTCIO_GPIO4_BIT) ? 1u : 0u;
}

static void latch_clear(void)
{
    REG_WRITE(RTC_GPIO_STATUS_W1TC_REG, RTCIO_GPIO4_BIT);
}

/* Any-edge detect on GPIO4: PIN4 int_type = 3 (bits [9:7]).  The RTC-IO status latch sets on
 * the edge whether or not any CPU interrupt is routed from it, so this probe polls the latch
 * and never registers an ISR (P16's routed-interrupt path measured 0 events). */
static void rtc_int_anyedge_enable(void)
{
    uint32_t v = REG_READ(RTC_GPIO_PIN4_REG);
    v &= ~(7u << 7);
    v |= (3u << 7);
    REG_WRITE(RTC_GPIO_PIN4_REG, v);
}

/* GUARDRAIL: rtc_gpio_init() alone leaves the pad input-disabled, and the RTC-IO edge detector
 * then has no input to watch; INPUT_OUTPUT sets fun_ie and mux_sel together.  A pad driven
 * digitally (mux_sel=0) may or may not reach RTCIO, hence the A/B self-test below. */
static int gpio4_setup_rtc(void)
{
    rtc_gpio_init(PIN);
    rtc_gpio_set_direction(PIN, RTC_GPIO_MODE_INPUT_OUTPUT);
    rtc_gpio_set_level(PIN, 0);
    rtc_int_anyedge_enable();
    latch_clear();
    s_digital_drive = 0;
    edge_high();
    uint32_t hi = latch_bit();
    uint32_t in_hi = (REG_READ(RTC_GPIO_IN_REG) & RTCIO_GPIO4_BIT) ? 1u : 0u;
    edge_low();
    printf("SELFTEST path=rtc_mux rise_latched=%" PRIu32 " in_hi=%" PRIu32
           " status=0x%08" PRIx32 "\n", hi, in_hi, REG_READ(RTC_GPIO_STATUS_REG));
    fflush(stdout);
    latch_clear();
    return hi;
}

static int gpio4_setup_digital(void)
{
    rtc_gpio_deinit(PIN);
    gpio_config_t cfg = {
        .pin_bit_mask = 1ull << PIN,
        .mode = GPIO_MODE_INPUT_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&cfg);
    rtc_int_anyedge_enable();
    latch_clear();
    s_digital_drive = 1;
    edge_high();
    uint32_t hi = latch_bit();
    edge_low();
    printf("SELFTEST path=digital rise_latched=%" PRIu32 " status=0x%08" PRIx32 "\n",
           hi, REG_READ(RTC_GPIO_STATUS_REG));
    fflush(stdout);
    latch_clear();
    return hi;
}

/* ---- ULP control ---- */

static void stage_ulp(void)
{
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(50));
    esp_task_wdt_reset();
    ESP_ERROR_CHECK(ulp_riscv_load_binary(ulp_main_bin_start,
                                          (size_t)(ulp_main_bin_end - ulp_main_bin_start)));
    /* GUARDRAIL: only write ULP words while the timer is stopped (P06 wedged the board by
     * writing a word the ULP was reading); every word below has one writer per phase. */
    wr(&ulp_wake_count, 0);
    wr(&ulp_ev_count, 0);
    wr(&ulp_last_status, 0);
    wr(&ulp_last_in, 0);
    wr(&ulp_period_cyc, 0);
    wr(&ulp_prev_cyc, 0);
    uint32_t *st = (uint32_t *)&ulp_statuses;
    uint32_t *cy = (uint32_t *)&ulp_cycles;
    for (uint32_t i = 0; i < RING; i++) {
        wr(st + i, 0);
        wr(cy + i, 0);
    }
}

static int wait_wakes(uint32_t target)
{
    int64_t t0 = esp_timer_get_time();
    while (rd(&ulp_wake_count) < target) {
        if (esp_timer_get_time() - t0 > WAKE_TMO_US) {
            printf("WARN wake_timeout want=%" PRIu32 " have=%" PRIu32 "\n",
                   target, rd(&ulp_wake_count));
            fflush(stdout);
            return 0;
        }
    }
    esp_task_wdt_reset();
    return 1;
}

static uint32_t status_hits(uint32_t w_from, uint32_t w_to)
{
    const volatile uint32_t *st = (const volatile uint32_t *)&ulp_statuses;
    uint32_t s = 0;
    for (uint32_t w = w_from; w < w_to; w++) {
        s += st[w & (RING - 1u)];
    }
    return s;
}

/* Bring the pin low and let two wakes drain any latch: every trial then starts from a known
 * level and a known-clean latch. */
static void drain(void)
{
    edge_low();
    wait_wakes(rd(&ulp_wake_count) + 2);
}

static void burst(uint32_t n_edges, uint32_t half_us)
{
    for (uint32_t i = 0; i < n_edges; i++) {
        if (i & 1u) {
            edge_low();
        } else {
            edge_high();
        }
        if (half_us) {
            esp_rom_delay_us(half_us);
        }
    }
}

/* Widths below a microsecond need a cycle-counted spin: esp_rom_delay_us(0) is not a delay. */
static inline void spin_ns(uint32_t ns)
{
    uint32_t cyc = (ns * 6u) / 25u + 1u;         /* 240 MHz: 1 ns = 0.24 cycle */
    uint32_t t0 = esp_cpu_get_cycle_count();
    while (esp_cpu_get_cycle_count() - t0 < cyc) {
    }
}

/* ---- 3: N edges during one ULP sleep ---- */
static void trial_coalesce(uint32_t n)
{
    drain();
    uint32_t e0 = rd(&ulp_ev_count);
    uint32_t w0 = rd(&ulp_wake_count);
    esp_rom_delay_us(300);                       /* clear the ULP's own read/clear window */
    burst(n, 0);
    wait_wakes(w0 + 2);
    uint32_t e1 = rd(&ulp_ev_count);
    printf("COALESCE n=%" PRIu32 " events=%" PRIu32 " wakes=%" PRIu32
           " hits=%" PRIu32 " status=0x%08" PRIx32 "\n",
           n, e1 - e0, rd(&ulp_wake_count) - w0, status_hits(w0, rd(&ulp_wake_count)),
           rd(&ulp_last_status));
    fflush(stdout);
}

/* ---- 4: rate sweep, 1000 (or as many as fit the clock) edges per sleep window ---- */
static void trial_rate(uint32_t n, uint32_t half_us, const char *tag)
{
    drain();
    uint32_t e0 = rd(&ulp_ev_count);
    uint32_t w0 = rd(&ulp_wake_count);
    esp_rom_delay_us(300);
    int64_t t0 = esp_timer_get_time();
    burst(n, half_us);
    int64_t dt = esp_timer_get_time() - t0;
    wait_wakes(w0 + 3);
    uint32_t e1 = rd(&ulp_ev_count);
    printf("RATE %s sent=%" PRIu32 " events=%" PRIu32 " lost=%" PRId32
           " span_us=%" PRId64 " wakes=%" PRIu32 "\n",
           tag, n, e1 - e0, (int32_t)((int64_t)n - (int64_t)(e1 - e0)), dt,
           rd(&ulp_wake_count) - w0);
    fflush(stdout);
}

/* ---- 3b: how narrow a pulse does the RTC domain still latch? ---- */
static void trial_width(uint32_t width_ns, uint32_t width_us)
{
    drain();
    uint32_t e0 = rd(&ulp_ev_count);
    uint32_t w0 = rd(&ulp_wake_count);
    esp_rom_delay_us(300);
    edge_high();
    if (width_us) {
        esp_rom_delay_us(width_us);
    } else {
        spin_ns(width_ns);
    }
    edge_low();
    wait_wakes(w0 + 3);
    uint32_t e1 = rd(&ulp_ev_count);
    printf("WIDTH ns=%" PRIu32 " us=%" PRIu32 " events=%" PRIu32 "\n",
           width_ns, width_us, e1 - e0);
    fflush(stdout);
}

/* ---- 5: edge -> wake latency.  One edge per sleep, phase offset swept across the period. ---- */
static void trial_latency(uint32_t off_us)
{
    /* The pin's level is flipped once per trial, so exactly one edge is driven here. */
    wait_wakes(rd(&ulp_wake_count) + 1);         /* just after a wake caught the last edge */
    int64_t t_obs = esp_timer_get_time();
    if (off_us) {
        esp_rom_delay_us(off_us);
    }
    uint32_t e0 = rd(&ulp_ev_count);
    int64_t t_edge;
    if (s_level) {
        edge_low();
        t_edge = esp_timer_get_time();
    } else {
        edge_high();
        t_edge = esp_timer_get_time();
    }
    while (rd(&ulp_ev_count) == e0) {
        if (esp_timer_get_time() - t_edge > WAKE_TMO_US) {
            printf("LAT off=%" PRIu32 " LOST\n", off_us);
            fflush(stdout);
            return;
        }
    }
    int64_t t_det = esp_timer_get_time();
    uint32_t lat = (uint32_t)(t_det - t_edge);
    if (s_nlat < 32) {
        s_lat[s_nlat++] = lat;
    }
    printf("LAT off_us=%" PRIu32 " lat_us=%" PRIu32 " obs_delay_us=%" PRId64 "\n",
           off_us, lat, t_edge - t_obs);
    fflush(stdout);
}

static uint32_t percentile(uint32_t *v, uint32_t n, uint32_t pct)
{
    if (n == 0) {
        return 0;
    }
    uint32_t i = (n * pct) / 100u;
    return v[i < n ? i : n - 1];
}

static void print_summary(void)
{
    /* Period as the ULP measured it: cycles between consecutive wakes. */
    const volatile uint32_t *cy = (const volatile uint32_t *)&ulp_cycles;
    uint32_t w = rd(&ulp_wake_count);
    uint32_t s[16];
    uint32_t n = 0;
    for (uint32_t k = 1; k <= 16 && k <= w; k++) {
        uint32_t c = cy[(w - k) & (RING - 1u)];
        if (c) {
            s[n++] = c;
        }
    }
    for (uint32_t i = 0; i < n; i++) {            /* insertion sort, n <= 16 */
        uint32_t x = s[i], j = i;
        while (j > 0 && s[j - 1] > x) {
            s[j] = s[j - 1];
            j--;
        }
        s[j] = x;
    }
    if (n) {
        uint32_t md = s[n / 2];
        /* 122.6 ULP cycles per RTC tick, 52.692 ns per cycle (P05) */
        printf("PERIOD ulp_cyc_med=%" PRIu32 " ticks_med=%" PRIu32 " us_med=%" PRIu32 "\n",
               md, md / 122u, (uint32_t)((uint64_t)md * 52692u / 1000000u));
    }
    for (uint32_t i = 0; i < s_nlat; i++) {
        uint32_t x = s_lat[i], j = i;
        while (j > 0 && s_lat[j - 1] > x) {
            s_lat[j] = s_lat[j - 1];
            j--;
        }
        s_lat[j] = x;
    }
    printf("LATENCY n=%" PRIu32 " min=%" PRIu32 " med=%" PRIu32 " p95=%" PRIu32
           " max=%" PRIu32 "\n",
           s_nlat,
           s_nlat ? s_lat[0] : 0,
           percentile(s_lat, s_nlat, 50),
           percentile(s_lat, s_nlat, 95),
           s_nlat ? s_lat[s_nlat - 1] : 0);
    printf("LATCH final_events=%" PRIu32 " final_status=0x%08" PRIx32
           " wakes=%" PRIu32 " digital_drive=%d\n",
           rd(&ulp_ev_count), rd(&ulp_last_status), rd(&ulp_wake_count), s_digital_drive);
    fflush(stdout);
}

static void wait_for_go(void)
{
    printf("P18 READY stage=console — send 'g' on UART0 (115200) to start\n");
    fflush(stdout);
    int got = 0;
    for (int i = 0; i < 200 && !got; i++) {      /* 200 x 40 ms = 8 s cap */
        uint8_t c = 0;
        if (uart_read_bytes(UART_NUM_0, &c, 1, pdMS_TO_TICKS(40)) == 1 && (c == 'g' || c == 'G')) {
            got = 1;
        }
        /* GUARDRAIL: the capture opens the port a second or two after the reset, so a single
         * banner is usually lost and a silent run looks like a wedged board.  Repeat it. */
        if (!got && (i % 25) == 24) {
            printf("P18 READY stage=console — send 'g' on UART0 (115200) to start\n");
            fflush(stdout);
        }
        esp_task_wdt_reset();
    }
    printf("P18 GO gate=%s\n", got ? "console" : "timeout");
    fflush(stdout);
}

void app_main(void)
{
    /* GUARDRAIL: watchdog goes up BEFORE UART and before any ULP call (P06: a hang in our own
     * code ate the console, so "chip wedged" and "app spinning" were indistinguishable). */
    esp_task_wdt_config_t wdt_cfg = {
        .timeout_ms = 25000,
        .idle_core_mask = 0,
        .trigger_panic = true,
    };
    esp_err_t wdt_err = esp_task_wdt_init(&wdt_cfg);
    if (wdt_err != ESP_OK) {
        wdt_err = esp_task_wdt_reconfigure(&wdt_cfg);
    }
    esp_task_wdt_add(NULL);
    esp_task_wdt_reset();

    printf("P18 BOOT stage=wdt wdt_init=%d reset_reason=%d\n",
           (int)wdt_err, (int)esp_reset_reason());
    fflush(stdout);

    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0));
    esp_task_wdt_reset();

    if (!gpio4_setup_rtc()) {
        gpio4_setup_digital();
    }
    s_level = 0;
    latch_clear();

    /* Polling granularity of the latency harness, measured rather than assumed. */
    int64_t pt0 = esp_timer_get_time();
    for (int i = 0; i < 1000; i++) {
        (void)rd(&ulp_ev_count);
    }
    printf("POLL us_per_1000_reads=%" PRId64 "\n", esp_timer_get_time() - pt0);
    fflush(stdout);

    wait_for_go();

    stage_ulp();
    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, ULP_PERIOD_US));
    ESP_ERROR_CHECK(ulp_riscv_run());
    /* GUARDRAIL: no GPIO wakeup is armed anywhere in this image — the ULP must be blind to the
     * edges and report them only at its next timer wake, or the coalescing number is a lie. */
    if (!wait_wakes(3)) {
        printf("P18 ABORT ulp did not wake\n");
        fflush(stdout);
        return;
    }
    printf("ULP running period_us=%" PRIu32 " wake_count=%" PRIu32 "\n",
           (uint32_t)ULP_PERIOD_US, rd(&ulp_wake_count));
    fflush(stdout);

    trial_coalesce(2);
    trial_coalesce(5);
    trial_coalesce(50);
    trial_coalesce(500);
    trial_coalesce(5000);

    trial_width(100000, 100);
    trial_width(30000, 30);
    trial_width(10000, 10);
    trial_width(3000, 3);
    trial_width(1000, 1);
    trial_width(300, 0);
    trial_width(100, 0);
    trial_width(30, 0);

    trial_rate(3, 500000, "1Hz");
    trial_rate(200, 5000, "100Hz");
    trial_rate(1000, 50, "10kHz");
    trial_rate(1000, 5, "100kHz");

    for (uint32_t off = 0; off < 6400; off += 800) {
        trial_latency(off);
        esp_task_wdt_reset();
    }

    /* 6: the latch must be clean after the ULP clears it: three quiet wakes, zero events. */
    drain();
    uint32_t e0 = rd(&ulp_ev_count);
    uint32_t w0 = rd(&ulp_wake_count);
    wait_wakes(w0 + 3);
    printf("CLEAN quiet_wakes=%" PRIu32 " events=%" PRIu32 " hits=%" PRIu32 "\n",
           rd(&ulp_wake_count) - w0, rd(&ulp_ev_count) - e0,
           status_hits(w0, rd(&ulp_wake_count)));
    print_summary();

    ulp_riscv_timer_stop();
    edge_low();
    latch_clear();
    printf("P18 done ulp_stopped=1 pin=low latch_cls=0\n");
    fflush(stdout);
}
