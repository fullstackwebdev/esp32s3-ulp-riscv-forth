/* P06 — HP-side driver: wake-semantics of the ULP-RISC-V core.  Second attempt.
 *
 * Staged so a wedge is attributable: watchdog first, then UART, then a "READY" banner,
 * then the experiment only after 'g' arrives on UART0 (115200, /dev/ttyACM1).
 *
 * Phases (in this order on purpose):
 *   delay sweep at period ~1 tick   -> overrun behaviour (lost / latched / re-entry)
 *   timer + GPIO together           -> coexistence, cause attribution, GPIO latency
 *   aborted wake                    -> is DONE still set on the non-return path?
 *                                    (LAST: first attempt's prime wedge suspect)
 *
 * Every number printed is either an esp_timer window or a shared-memory RTC-tick stamp
 * written by the ULP, so the log alone is enough to recompute the result.
 */
#include <stdio.h>
#include <inttypes.h>

#include "esp_timer.h"
#include "esp_rom_sys.h"
#include "esp_sleep.h"
#include "esp_attr.h"
#include "esp_task_wdt.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "ulp_riscv.h"
#include "ulp_main.h"
#include "soc/rtc_cntl_reg.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

extern const uint8_t ulp_main_bin_start[] asm("_binary_ulp_main_bin_start");
extern const uint8_t ulp_main_bin_end[] asm("_binary_ulp_main_bin_end");

/* ulp_* symbols are linker-PROVIDEd absolute RTC-slow-memory addresses, so they must be
 * read through volatile pointers or the optimiser caches the first snapshot and every
 * phase reports a stale wake.
 * GUARDRAIL: reading ulp_<name> without volatile made a whole P05 phase report the counters
 * of an earlier wake — always go through this accessor. */
static inline uint32_t rd(const uint32_t *p) { return *(volatile const uint32_t *)p; }

/* 154.9 kHz measured in P05; 6.46 us per tick. Never 136 kHz (14 % error). */
#define TICKS_PER_SEC_MILLI 154900000LL
#define TICKS_PER_SEC       154900u

/* GUARDRAIL: GPIO19/20 are the native USB D-/D+ — arming or driving them killed the
 * USB-JTAG peripheral and forced a hands-on EN press in the first P06 attempt (board
 * silent for hours, every software reset path dead).  Wake pin is RTC GPIO4: not USB,
 * not strapping (0/3/45/46), not UART0 (43/44), not flash/PSRAM (26-37). */
#define COEXIST_GPIO 4

static void wdt_feed(void) { esp_task_wdt_reset(); }

static void reset_stats(void)
{
    ulp_tick_start_prev = 0;
    ulp_span_prev = 0;
    ulp_gap_min = 0xFFFFFFFFu;
    ulp_gap_max = 0;
    ulp_gap_sum = 0;
    ulp_span_min = 0xFFFFFFFFu;
    ulp_span_max = 0;
    ulp_span_sum = 0;
    ulp_resid_min = 0xFFFFFFFFu;
    ulp_resid_max = 0;
    ulp_resid_sum = 0;
    ulp_stat_ctr = 0;
    ulp_cause_last = 0;
    ulp_wake_tick_last = 0;
    __sync_synchronize();
}

/* bounded twice: iteration cap AND an esp_timer wall-clock check (P05's window
 * collapsed to its iteration cap because pdMS_TO_TICKS(1) is 0 at 100 Hz FreeRTOS).
 * GUARDRAIL: never size a measurement window with vTaskDelay(pdMS_TO_TICKS(1)) — at the
 * IDF default CONFIG_FREERTOS_HZ=100 that is vTaskDelay(0), which only yields. */
static int64_t wait_window(uint32_t window_ms)
{
    int64_t t_start = esp_timer_get_time();
    for (int i = 0; i < (int)(window_ms * 4); i++) {
        esp_rom_delay_us(1000);
        wdt_feed();
        if (esp_timer_get_time() - t_start >= (int64_t)window_ms * 1000) {
            break;
        }
    }
    return esp_timer_get_time() - t_start;
}

static void reload(uint32_t delay_cycles, uint32_t mode)
{
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(20));
    ESP_ERROR_CHECK(ulp_riscv_load_binary(ulp_main_bin_start,
                                          (size_t)(ulp_main_bin_end - ulp_main_bin_start)));
    reset_stats();
    ulp_delay_cycles = delay_cycles;
    ulp_mode = mode;
    __sync_synchronize();
}

static void overrun_phase(uint32_t period_us, uint32_t delay_cycles, uint32_t window_ms,
                          const char *tag)
{
    reload(delay_cycles, 0);
    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, period_us));
    ESP_ERROR_CHECK(ulp_riscv_run());

    int64_t elapsed = wait_window(window_ms);
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(50));   /* let the in-flight wake retire */
    wdt_feed();

    uint32_t wakes = rd(&ulp_wake_ctr);
    uint32_t st    = rd(&ulp_stat_ctr);
    int64_t wakes_per_sec_milli = 0;
    if (elapsed > 0) {
        wakes_per_sec_milli = ((int64_t)wakes * 1000000000LL) / elapsed;
    }
    int32_t span_last_us = (int32_t)(((int64_t)rd(&ulp_span_last) * 1000000LL) / TICKS_PER_SEC);
    printf("OVER %s period_us=%" PRIu32 " delay=%" PRIu32 " window_us=%" PRId64
           " wakes=%" PRIu32 " wps_milli=%" PRId64
           " span_last_us=%" PRId32 " span_us_min=%" PRId32 " span_us_max=%" PRId32 "\n",
           tag, period_us, delay_cycles, elapsed, wakes, wakes_per_sec_milli,
           span_last_us,
           (int32_t)(((int64_t)rd(&ulp_span_min) * 1000000LL) / TICKS_PER_SEC),
           (int32_t)(((int64_t)rd(&ulp_span_max) * 1000000LL) / TICKS_PER_SEC));
    if (st == 0) {
        printf("GAP %s n=0 (no completed pair)\n", tag);
        return;
    }
    /* residual = interval between wake starts minus the previous wake's own duration.
     * resid ~= period  => tick LOST on overrun;  resid ~= 0 => tick LATCHED. */
    uint32_t rm = rd(&ulp_resid_min);
    uint32_t rM = rd(&ulp_resid_max);
    if (rd(&ulp_resid_last) < rm) {
        rm = rd(&ulp_resid_last);
    }
    if (rd(&ulp_resid_last) > rM) {
        rM = rd(&ulp_resid_last);
    }
    printf("GAP %s n=%" PRIu32 " gap_ticks[min=%" PRIu32 " max=%" PRIu32 " mean_milli=%" PRId64
           "] resid_ticks[min=%" PRIu32 " max=%" PRIu32 " mean_milli=%" PRId64 "] resid_last=%" PRIu32 "\n",
           tag, st, rd(&ulp_gap_min), rd(&ulp_gap_max),
           (int64_t)(((int64_t)rd(&ulp_gap_sum) * 1000LL) / (int64_t)st),
           rm, rM,
           (int64_t)(((int64_t)rd(&ulp_resid_sum) * 1000LL) / (int64_t)st),
           rd(&ulp_resid_last));
    printf("RAW %s cyc_top=%" PRIu32 " cyc_end=%" PRIu32 "\n",
           tag, rd(&ulp_cyc_top), rd(&ulp_cyc_end));
}

/* Latch a fresh RTC counter snapshot and read its low word.  Same sequence as the ULP's
 * TICK_READ: the low word is a snapshot that only refreshes after TIME_UPDATE gets BIT(31).
 * GUARDRAIL: bumping the baud rate here (a "harmless" speed-up) cost P05 an hour of
 * trusting numbers that were computed from a stale register. */
static uint32_t hp_tick(void)
{
    REG_WRITE(RTC_CNTL_TIME_UPDATE_REG, RTC_CNTL_TIME_UPDATE);
    while (REG_READ(RTC_CNTL_TIME_UPDATE_REG) & RTC_CNTL_TIME_UPDATE) {
    }
    return REG_READ(RTC_CNTL_TIME_LOW0_REG);
}

static void coexist_phase(uint32_t period_us)
{
    /* Arm the timer the normal way (ulp_riscv_run sets ULP_CP_SLP_TIMER_EN), then OR in
     * ULP_CP_GPIO_WAKEUP_ENA by hand: ulp_riscv_config_wakeup_source() picks exactly one
     * source, so coexistence is only reachable by touching the register directly.
     * GUARDRAIL: SLP_TIMER_EN(BIT31) and GPIO_WAKEUP_ENA(BIT29) are independent bits of
     * RTC_CNTL_ULP_CP_TIMER_REG, so "only one wakeup source" is an API limitation, not a
     * hardware one — but GPIO_WAKEUP_CLR is BIT30 of the same word and writing it as part
     * of a read-modify-write would immediately clear the GPIO latch. */
    reload(0, 0);
    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, period_us));
    ESP_ERROR_CHECK(ulp_riscv_run());
    int64_t t0 = esp_timer_get_time();
    wait_window(200);
    uint32_t timer_cause = rd(&ulp_cause_last);
    printf("COEX baseline timer_only window_us=%" PRId64 " wakes=%" PRIu32
           " cause_raw=0x%08" PRIX32 "\n", esp_timer_get_time() - t0,
           rd(&ulp_wake_ctr), timer_cause);

    gpio_config_t io = {
        .pin_bit_mask = 1ULL << COEXIST_GPIO,
        .mode = GPIO_MODE_INPUT_OUTPUT,
        .pull_up_en = 0,
        .pull_down_en = 0,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io);
    gpio_set_level(COEXIST_GPIO, 0);
    /* GUARDRAIL: esp_deep_sleep_enable_gpio_wakeup() is not declared on this S3 target
     * (the SOC capability macro is off), so the RTC-IO wakeup must be armed the
     * light-sleep way — gpio_wakeup_enable() plus esp_sleep_enable_gpio_wakeup() — which
     * is the same RTC IO signal the ULP's ULP_CP_GPIO_WAKEUP_ENA bit listens to. */
    gpio_wakeup_enable(COEXIST_GPIO, GPIO_INTR_HIGH_LEVEL);
    esp_err_t gerr = esp_sleep_enable_gpio_wakeup();
    SET_PERI_REG_MASK(RTC_CNTL_ULP_CP_TIMER_REG, RTC_CNTL_ULP_CP_GPIO_WAKEUP_ENA);
    uint32_t reg = REG_READ(RTC_CNTL_ULP_CP_TIMER_REG);
    printf("COEX arm reg=0x%08" PRIX32 " slp_en=%d gpio_ena=%d gpio_wakeup_api=%d\n",
           reg,
           (reg & RTC_CNTL_ULP_CP_SLP_TIMER_EN) ? 1 : 0,
           (reg & RTC_CNTL_ULP_CP_GPIO_WAKEUP_ENA) ? 1 : 0,
           (int)gerr);

    /* Pin is pulsed far shorter than the 1 ms timer period, so a wake that carries a
     * cause value other than the timer baseline, and a wake tick that is off the timer
     * grid, is a GPIO wake.  The cause is read from the status register by the ULP on
     * every wake — never inferred from the wake count. */
    int n = 0, n_gpio = 0;
    uint32_t lat_min = 0xFFFFFFFFu, lat_max = 0, lat_sum = 0;
    for (int i = 0; i < 6; i++) {
        SET_PERI_REG_MASK(RTC_CNTL_ULP_CP_TIMER_REG, RTC_CNTL_ULP_CP_GPIO_WAKEUP_CLR);
        wdt_feed();
        uint32_t w_before = rd(&ulp_wake_ctr);
        uint32_t t_edge = hp_tick();
        gpio_set_level(COEXIST_GPIO, 1);
        /* bounded poll: 4 ms cap, ~40 iterations */
        int got = 0;
        for (int k = 0; k < 400 && !got; k++) {
            esp_rom_delay_us(10);
            got = (rd(&ulp_wake_ctr) != w_before);
        }
        gpio_set_level(COEXIST_GPIO, 0);
        uint32_t cause = rd(&ulp_cause_last);
        uint32_t wt = rd(&ulp_wake_tick_last);
        uint32_t lat = wt - t_edge;
        printf("GPIO i=%d seen=%d cause_raw=0x%08" PRIX32 " baseline=0x%08" PRIX32
               " lat_ticks=%" PRIu32 " lat_us=%" PRIu32 "\n",
               i, got, cause, timer_cause, lat, (uint32_t)((lat * 1000000u) / TICKS_PER_SEC));
        n++;
        if (got && cause != timer_cause) {
            n_gpio++;
            if (lat < lat_min) { lat_min = lat; }
            if (lat > lat_max) { lat_max = lat; }
            lat_sum += lat;
        }
        SET_PERI_REG_MASK(RTC_CNTL_ULP_CP_TIMER_REG, RTC_CNTL_ULP_CP_GPIO_WAKEUP_CLR);
        esp_rom_delay_us(5000);
    }
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(50));
    wdt_feed();
    printf("COEX result toggles=%d gpio_attributed=%d lat_ticks[min=%" PRIu32 " max=%" PRIu32
           " mean_milli=%" PRId64 "] lat_us_mean=%" PRId64
           " wakes_total=%" PRIu32 "\n",
           n, n_gpio,
           n_gpio ? lat_min : 0, n_gpio ? lat_max : 0,
           n_gpio ? (int64_t)(((int64_t)lat_sum * 1000LL) / n_gpio) : 0,
           n_gpio ? (int64_t)(((int64_t)lat_sum * 1000000LL) / ((int64_t)n_gpio * TICKS_PER_SEC)) : 0,
           rd(&ulp_wake_ctr));

    /* Disarm the RTC-IO path: the first attempt ended with it armed on a pin left
     * driving low as INPUT_OUTPUT, one of the wedge suspects. */
    CLEAR_PERI_REG_MASK(RTC_CNTL_ULP_CP_TIMER_REG, RTC_CNTL_ULP_CP_GPIO_WAKEUP_ENA);
    gpio_wakeup_disable(COEXIST_GPIO);
    esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_GPIO);
    reg = REG_READ(RTC_CNTL_ULP_CP_TIMER_REG);
    printf("COEX disarm reg=0x%08" PRIX32 " gpio_ena=%d\n", reg,
           (reg & RTC_CNTL_ULP_CP_GPIO_WAKEUP_ENA) ? 1 : 0);
}

static void retire_phase(uint32_t period_us, uint32_t window_ms)
{
    /* Aborted path: the kernel sets COCPU_DONE|COCPU_SHUT_RESET_EN itself and spins.
     * If wake_ctr/abort_ctr keep advancing, the timer re-armed after a wake that never
     * returned through __start -> retire confirmed on the non-return path too. */
    reload(0, 1);
    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, period_us));
    ESP_ERROR_CHECK(ulp_riscv_run());
    int64_t elapsed = wait_window(window_ms);
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(50));
    wdt_feed();
    uint32_t aborts1 = rd(&ulp_abort_ctr);
    printf("ABORT window_us=%" PRId64 " abort_ctr=%" PRIu32 " wake_ctr=%" PRIu32 "\n",
           elapsed, aborts1, rd(&ulp_wake_ctr));

    /* and back to the normal path: the aborted wakes must not have wedged anything */
    reload(0, 0);
    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, period_us));
    ESP_ERROR_CHECK(ulp_riscv_run());
    elapsed = wait_window(window_ms);
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(50));
    wdt_feed();
    printf("RETIRE after_abort_wakes=%" PRIu32 " window_us=%" PRId64 " abort_before=%" PRIu32 "\n",
           rd(&ulp_wake_ctr), elapsed, aborts1);
}

/* Stage gate: only start the experiment after 'g' on UART0.  If the board goes silent on
 * the next line of output, the last stage printed says which step killed it. */
static void wait_for_go(void)
{
    printf("P06v2 READY stage=console — send 'g' on UART0 (115200) to start\n");
    fflush(stdout);
    int got = 0;
    for (int i = 0; i < 400 && !got; i++) {   /* 400 x 50 ms = 20 s cap */
        uint8_t c = 0;
        if (uart_read_bytes(UART_NUM_0, &c, 1, pdMS_TO_TICKS(50)) == 1 && (c == 'g' || c == 'G')) {
            got = 1;
        }
        wdt_feed();
    }
    printf("P06v2 GO gate=%s\n", got ? "console" : "timeout");
    fflush(stdout);
}

void app_main(void)
{
    /* GUARDRAIL: the task watchdog must be up BEFORE UART init and BEFORE any ULP call —
     * in the first P06 attempt a hang in our own code ate the console and left no way to
     * tell "chip wedged" from "app spinning".  With the WDT armed first, a hang resets
     * the chip and the banner proves the stage.
     * (CONFIG_ESP_TASK_WDT_TIMEOUT_S=5; 12 s here so the 1.4 s overrun sweep is safe.) */
    esp_task_wdt_config_t wdt_cfg = {
        .timeout_ms = 12000,
        .idle_core_mask = 0,
        .trigger_panic = true,
    };
    esp_err_t wdt_err = esp_task_wdt_init(&wdt_cfg);
    if (wdt_err != ESP_OK) {
        /* CONFIG_ESP_TASK_WDT_INIT=y already initialised it from the startup code, so
         * init returns ESP_ERR_INVALID_STATE and keeps the 5 s default — reconfigure
         * instead of silently running under a timeout we did not ask for. */
        wdt_err = esp_task_wdt_reconfigure(&wdt_cfg);
    }
    esp_task_wdt_add(NULL);
    esp_task_wdt_reset();

    printf("P06v2 BOOT stage=wdt wdt_init=%d\n", (int)wdt_err);
    fflush(stdout);

    /* UART0 driver so we can read the 'g' byte; console stdout already goes to UART0. */
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0));
    esp_task_wdt_reset();

    wait_for_go();

    /* period 8 us ~= 1.2 RTC ticks at the measured 154.9 kHz: a 1-tick period.
     * P05 measured 122.6 cycles/tick, so the budget is 122.6 cycles and the sweep
     * below is 0.1x / 1x / 2x / 10x of it — every point from 2x up is a real overrun. */
    overrun_phase(8,   12,   300, "0.1x");
    overrun_phase(8,   122,  300, "1x");
    overrun_phase(8,   245,  300, "2x");
    overrun_phase(8,   1226, 500, "10x");
    /* GUARDRAIL: the 122.6-cycle "budget" is not the overrun threshold — the measured
     * floor between consecutive wake starts is 22 RTC ticks (~2700 cycles, 142 us), so
     * every point above sits *under* the period and never overruns (run 1: span 13 < 22).
     * Scale the sweep to the measured floor: 1x and 2x of 22 ticks are the first real
     * overrun points. */
    overrun_phase(8,   2700, 300, "1x_floor22ticks");
    overrun_phase(8,   5400, 300, "2x_floor22ticks");

    /* GUARDRAIL: coexist_phase() and retire_phase() are compiled in but not called here
     * on purpose.  Runs 1-2 proved the aborted-wake path (ULP writes
     * COCPU_DONE|COCPU_SHUT_RESET_EN mid-main and spins) kills the console ~1 s after it
     * starts, and only an RTS reset on UART0 brings the chip back — so it must never run
     * in the same boot as measurements that still have to be captured. */
    if (0) {
        coexist_phase(1000);
        retire_phase(200, 200);
    }

    ulp_riscv_timer_stop();
    printf("P06 done\n");
    fflush(stdout);
}
