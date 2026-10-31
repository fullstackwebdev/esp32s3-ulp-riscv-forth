/* P23 — which signal path from the ULP to the HP actually works?
 *
 * P16 could not fire its RTCIO-GPIO doorbell (isr_count=0 over 200 edges, two muxes).  This
 * image tests the four candidate paths, 200 round trips each where the path allows it:
 *
 *   A  polling req_seq from a task                      (control, P16 = 144 us)
 *   B  ulp_riscv_wakeup_main_processor() -> RTC_CNTL_COCPU_INT_ST -> ulp_riscv_isr_register()
 *      -> blocked FreeRTOS task
 *   C  the same call waking the chip from light sleep
 *   D  the same call waking the chip from deep sleep (each wake is a full HP boot)
 *
 * Staged so a wedge is attributable: watchdog first, then UART, then banner, then 'g'.
 */
#include <stdio.h>
#include <string.h>
#include <inttypes.h>

#include "esp_timer.h"
#include "esp_rom_sys.h"
#include "esp_attr.h"
#include "esp_system.h"
#include "esp_sleep.h"
#include "esp_task_wdt.h"
#include "driver/uart.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "ulp_riscv.h"
#include "ulp_main.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

extern const uint8_t ulp_main_bin_start[] asm("_binary_ulp_main_bin_start");
extern const uint8_t ulp_main_bin_end[] asm("_binary_ulp_main_bin_end");

/* ulp_* are linker-PROVIDEd absolute RTC-slow-memory addresses: read through a volatile
 * pointer or the optimiser caches the first snapshot.
 * GUARDRAIL: reading ulp_<name> without volatile made a whole P05 phase report counters
 * from an earlier wake — always go through this accessor. */
static inline uint32_t rd(const uint32_t *p) { return *(volatile const uint32_t *)p; }
static inline void wr(uint32_t *p, uint32_t v) { *(volatile uint32_t *)p = v; __sync_synchronize(); }

#define PAGE_BYTES    512u
#define WINDOW_BYTES  2048u
#define N_ITER        200u
#define DEEP_ROUNDS   2u                  /* deep-sleep wakes measured; each one = a full boot */
#define DEEP_GUARD_US 1500000             /* timer wakeup: proves the ULP never came */
#define LIGHT_GUARD_US 30000              /* 30 ms: light sleep must be a fast path or not at all */

static uint8_t s_pages[4][PAGE_BYTES];
static SemaphoreHandle_t s_doorbell;
/* 0 = server task polls, 1 = server task blocks on the ULP ISR, 2 = server task parked and
 * the main task serves after each sleep wake (no two writers on rsp_*). */
static volatile int s_server_mode;
static volatile uint32_t s_sw_isr;        /* RTC COCPU ISR fires */
static volatile int s_finished;
static uint32_t s_last_seq;

RTC_DATA_ATTR static uint32_t s_deep_rounds;   /* survives deep sleep */
RTC_DATA_ATTR static uint32_t s_deep_wakes;

static void fill_pages(void)
{
    for (uint32_t pg = 0; pg < 4; pg++) {
        for (uint32_t i = 0; i < PAGE_BYTES; i++) {
            s_pages[pg][i] = (uint8_t)((pg * 37u) + i * 7u + 1u);
        }
        uint32_t tag = pg;                     /* page index in word 0 = stale-page marker */
        memcpy(&s_pages[pg][0], &tag, 4);
    }
}

static const char *st_name(uint32_t s)
{
    switch (s) {
    case 0: return "OK";
    case 1: return "TIMEOUT_NO_ANSWER";
    case 2: return "CHECKSUM_REJECTED";
    case 3: return "WRONG_PAGE";
    default: return "UNDEFINED";
    }
}

static uint32_t chk512(const uint8_t *p)
{
    uint32_t a = 0;
    for (int i = 0; i < 128; i++) {
        uint32_t w;
        memcpy(&w, p + 4 * i, 4);
        a = (a << 1) | (a >> 31);
        a ^= w;
    }
    return a;
}

/* One service: bounds check, copy 512 B, checksum, answer.  R6 forbids anything else. */
static void serve(uint32_t seq)
{
    uint32_t addr = rd(&ulp_req_addr);
    if (addr > WINDOW_BYTES - PAGE_BYTES) {
        wr(&ulp_rsp_status, 2);
        wr(&ulp_rsp_seq, seq);
        return;
    }
    const uint8_t *src = s_pages[(addr >> 9) & 3u];
    /* GUARDRAIL: the mapgen symbol is the *address* of the ULP variable, so `(void *)ulp_page`
     * is the uint32 stored there (0 at boot) and memcpy(..., 512) faults.  Always `&ulp_<name>`. */
    memcpy((void *)&ulp_page, src, PAGE_BYTES);
    wr(&ulp_rsp_chk, chk512((const uint8_t *)&ulp_page));
    wr(&ulp_rsp_status, 1);
    wr(&ulp_rsp_seq, seq);
}

static void serve_task(void *arg)
{
    uint32_t last = 0;
    for (;;) {
        if (s_finished) {
            printf("P23 SERVER stopped\n");
            fflush(stdout);
            vTaskDelete(NULL);
        }
        if (s_server_mode == 2) {               /* parked: the main task serves after a wake */
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if (s_server_mode == 1) {
            /* GUARDRAIL: bounded take, never portMAX_DELAY — a missed doorbell must show up
             * as a named timeout, not a task that hangs the phase (P06 wedge). */
            if (xSemaphoreTake(s_doorbell, pdMS_TO_TICKS(400)) != pdTRUE) {
                continue;
            }
        }
        uint32_t seq = rd(&ulp_req_seq);
        if (seq == 0u || seq == last) {
            continue;
        }
        last = seq;
        serve(seq);
    }
}

/* Path 1/2/3 ISR: the RTC COCPU interrupt.  IDF's rtc_isr dispatch clears the status bits
 * after the handler returns, so nothing here touches RTC_CNTL_INT_CLR. */
static void IRAM_ATTR ulp_sw_isr(void *arg)
{
    BaseType_t hp = pdFALSE;
    s_sw_isr++;
    /* GUARDRAIL: the COCPU trap status bit has no stable reset value, so enabling the TRAP
     * mask on this silicon is an interrupt storm that starves every task and turns the run
     * into a 25 s task-WDT reset loop with no console output.  Count in the ISR and, past
     * any plausible doorbell rate, mask the RTC interrupt so the board stays reachable. */
    if (s_sw_isr == 50000u) {
        REG_WRITE(RTC_CNTL_INT_ENA_REG, 0);
    }
    xSemaphoreGiveFromISR(s_doorbell, &hp);
    if (hp) {
        portYIELD_FROM_ISR();
    }
}

/* Register state at the moment of failure — the brief's "why as far as the hardware will say". */
static void print_regs(const char *tag)
{
    uint32_t st  = REG_READ(RTC_CNTL_INT_ST_REG);
    uint32_t ena = REG_READ(RTC_CNTL_INT_ENA_REG);
    uint32_t state0 = REG_READ(RTC_CNTL_STATE0_REG);
    printf("REGS %s INT_ST=0x%08" PRIx32 " cocpu_st=%d swcpu_pending=%d INT_ENA=0x%08" PRIx32
           " cocpu_ena=%d\n",
           tag, st,
           (st & RTC_CNTL_COCPU_INT_ST_M) ? 1 : 0,
           (state0 & RTC_CNTL_SW_CPU_INT) ? 1 : 0,
           ena, (ena & RTC_CNTL_COCPU_INT_ST_M) ? 1 : 0);
}

/* GUARDRAIL: the HP must never write a word the ULP may be reading while the ULP is live
 * (P06 wedged the board that way).  Staging happens only after ulp_riscv_timer_stop() and a
 * settle delay, never during a pass. */
static void stage(uint32_t mode, uint32_t n_iter)
{
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(50));
    esp_task_wdt_reset();
    ESP_ERROR_CHECK(ulp_riscv_load_binary(ulp_main_bin_start,
                                          (size_t)(ulp_main_bin_end - ulp_main_bin_start)));
    wr(&ulp_mode, mode);
    wr(&ulp_n_iter, n_iter);
    wr(&ulp_req_seq, 0);
    wr(&ulp_req_addr, 0);
    wr(&ulp_rsp_seq, 0);
    wr(&ulp_rsp_status, 0);
    wr(&ulp_rsp_chk, 0);
    wr(&ulp_iters_done, 0);
    wr(&ulp_phase_done, 0);
    /* GUARDRAIL: ulp_deltas is an array symbol, so `&ulp_deltas + i` walks i*200 words
     * past it and silently zeroes unrelated RTC memory — index through a uint32_t*. */
    uint32_t *deltas = (uint32_t *)&ulp_deltas;
    for (uint32_t i = 0; i < N_ITER; i++) {
        wr(deltas + i, 0);
    }
    s_last_seq = 0;
}

/* 122.6 ULP cycles per RTC tick, 6.46 us per tick, 52.692 ns per cycle (P05). */
static void print_stats(const char *tag, int done, uint32_t pass_ms, uint32_t hp_isr)
{
    static uint32_t v[N_ITER];
    uint32_t n = 0, nok = 0, attempted = rd(&ulp_iters_done);
    for (uint32_t i = 0; i < N_ITER; i++) {
        uint32_t d = ((const uint32_t *)&ulp_deltas)[i];
        if (d != 0u) {
            v[n++] = d;
            if (((const uint8_t *)&ulp_statii)[i] == 0u) {
                nok++;
            }
        }
    }
    printf("STATS %s fired=%" PRIu32 " attempted=%" PRIu32 " ok=%" PRIu32 " pass_done=%d"
           " pass_ms=%" PRIu32 " hp_isr=%" PRIu32 " req_seq=%" PRIu32 " rsp_seq=%" PRIu32 "\n",
           tag, n, attempted, nok, done, pass_ms, hp_isr,
           rd(&ulp_req_seq), rd(&ulp_rsp_seq));
    if (n == 0) {
        return;
    }
    for (uint32_t i = 0; i < n; i++) {                 /* insertion sort: n <= 200 */
        uint32_t x = v[i], j = i;
        while (j > 0 && v[j - 1] > x) {
            v[j] = v[j - 1];
            j--;
        }
        v[j] = x;
    }
    uint32_t mn = v[0], md = v[n / 2], p95 = v[(n * 95u) / 100u], mx = v[n - 1];
    printf("CYC %s min=%" PRIu32 " med=%" PRIu32 " p95=%" PRIu32 " max=%" PRIu32 "\n",
           tag, mn, md, p95, mx);
    /* ticks = cycles / 122.6  (x100), us = cycles * 52.692 ns (x1000) */
    printf("MICRO %s ticks_med=%" PRIu32 " ticks_p95=%" PRIu32 " ticks_max=%" PRIu32
           " us_med=%" PRIu32 " us_p95=%" PRIu32 " us_max=%" PRIu32 "\n",
           tag,
           md * 100u / 1226u, p95 * 100u / 1226u, mx * 100u / 1226u,
           md * 52692u / 1000000u, p95 * 52692u / 1000000u, mx * 52692u / 1000000u);
}

static void wait_for_go(void)
{
    printf("P23 READY stage=console — send 'g' on UART0 (115200) to start\n");
    fflush(stdout);
    int got = 0;
    for (int i = 0; i < 200 && !got; i++) {      /* 200 x 40 ms = 8 s cap */
        uint8_t c = 0;
        if (uart_read_bytes(UART_NUM_0, &c, 1, pdMS_TO_TICKS(40)) == 1 && (c == 'g' || c == 'G')) {
            got = 1;
        }
        /* GUARDRAIL: the capture opens the port a second or two after the flash reset, so a
         * banner printed once is usually lost and a silent run looks like a wedged board.
         * Repeat it once a second for the whole gate. */
        if (!got && (i % 25) == 24) {
            printf("P23 READY stage=console — send 'g' on UART0 (115200) to start\n");
            fflush(stdout);
        }
        esp_task_wdt_reset();
    }
    printf("P23 GO gate=%s\n", got ? "console" : "timeout");
    fflush(stdout);
}

/* ---- A/B: HP awake, main task just waits for the ULP pass to finish ---- */
static int run_awake(uint32_t mode, const char *tag)
{
    stage(mode, N_ITER);
    s_server_mode = (mode == 0u) ? 0 : 1;
    s_sw_isr = 0;
    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, 1000000));
    ESP_ERROR_CHECK(ulp_riscv_run());
    int64_t t0 = esp_timer_get_time();
    int done = 0;
    while (esp_timer_get_time() - t0 < 8000000) {
        esp_task_wdt_reset();
        if (rd(&ulp_phase_done) == 1u) {
            done = 1;
            break;
        }
        esp_rom_delay_us(200);
    }
    uint32_t ms = (uint32_t)((esp_timer_get_time() - t0) / 1000);
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(50));
    print_stats(tag, done, ms, s_sw_isr);
    if (!done || s_sw_isr == 0) {
        print_regs(tag);
    }
    s_server_mode = 0;
    return done;
}

/* ---- C: light sleep ---- */
static int run_light_sleep(void)
{
    stage(2, N_ITER);
    s_server_mode = 2;                       /* parked: only this task may write rsp_* */
    s_sw_isr = 0;
    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, 1000000));
    ESP_ERROR_CHECK(ulp_riscv_run());
    int64_t t0 = esp_timer_get_time();
    uint32_t wakes = 0, timer_wakes = 0;
    int done = 0;
    for (uint32_t i = 0; i < N_ITER; i++) {
        esp_task_wdt_reset();
        /* GUARDRAIL: a COCPU status bit left set by the previous wake makes
         * esp_light_sleep_start() return immediately with cause=UNDEFINED and the core never
         * actually sleeps — the phase then reads as "the doorbell stopped working" when the
         * truth is a stale flag.  Clear the RTC interrupt latches before every sleep. */
        REG_WRITE(RTC_CNTL_INT_CLR_REG, UINT32_MAX);
        esp_sleep_enable_ulp_wakeup();               /* RTC_COCPU_TRIG_EN */
        esp_sleep_enable_timer_wakeup(LIGHT_GUARD_US);
        esp_light_sleep_start();
        esp_sleep_wakeup_cause_t c = esp_sleep_get_wakeup_cause();
        esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_TIMER);
        uint32_t seq = rd(&ulp_req_seq);
        if (c == ESP_SLEEP_WAKEUP_TIMER) {
            /* The guard timer fired and no doorbell did: the ULP's signal cannot leave the
             * RTC domain.  Record the hardware's own view and stop — 200 more 30 ms guard
             * timeouts say nothing new. */
            timer_wakes++;
            printf("LIGHT guard_timer_wake c=%d seq=%" PRIu32 " rsp=%" PRIu32
                   " us=%" PRId64 "\n", (int)c, seq, rd(&ulp_rsp_seq),
                   esp_timer_get_time() - t0);
            print_regs("light_sleep_guard_wake");
            break;
        }
        wakes++;
        if (seq != 0u && seq != s_last_seq) {
            s_last_seq = seq;
            serve(seq);
        }
        if (rd(&ulp_phase_done) == 1u) {
            done = 1;
            break;
        }
    }
    uint32_t ms = (uint32_t)((esp_timer_get_time() - t0) / 1000);
    if (rd(&ulp_phase_done) == 1u) {
        done = 1;
    }
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(50));
    if (timer_wakes) {
        /* Someone else answered the door: prove the ULP kept running while the HP slept, so
         * the failure is the signal path and not the ULP. */
        ulp_riscv_timer_resume();
        vTaskDelay(pdMS_TO_TICKS(60));
        ulp_riscv_timer_stop();
    }
    printf("LIGHT sleeper_wakes=%" PRIu32 " guard_timer_wakes=%" PRIu32 "\n", wakes, timer_wakes);
    print_stats("C_light", done, ms, s_sw_isr);
    s_server_mode = 0;
    return done;
}

/* ---- D: deep sleep.  Each wake is a boot, so the counters live in RTC memory. ---- */
static void enter_deep(int first)
{
    if (first) {
        stage(3, DEEP_ROUNDS);
        s_server_mode = 2;
        ESP_ERROR_CHECK(ulp_set_wakeup_period(0, 1000000));
        ESP_ERROR_CHECK(ulp_riscv_run());
        printf("DEEP armed rounds=%" PRIu32 " guard_us=%d\n", (uint32_t)DEEP_ROUNDS, DEEP_GUARD_US);
        fflush(stdout);
    }
    esp_sleep_enable_ulp_wakeup();
    esp_sleep_enable_timer_wakeup(DEEP_GUARD_US);
    esp_deep_sleep_start();                  /* does not return */
}

void app_main(void)
{
    /* GUARDRAIL: the task watchdog goes up BEFORE UART and before any ULP call — in the
     * first P06 attempt a hang in our own code ate the console and left no way to tell
     * "chip wedged" from "app spinning". */
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

    printf("P23 BOOT stage=wdt wdt_init=%d reset_reason=%d\n", (int)wdt_err, (int)esp_reset_reason());
    fflush(stdout);

    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0));
    esp_task_wdt_reset();

    esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();

    /* ---- deep-sleep wake boots land here: no 'g' will arrive, report and re-arm ---- */
    if (cause != ESP_SLEEP_WAKEUP_UNDEFINED) {
        uint32_t seq = rd(&ulp_req_seq);
        printf("DEEP WAKE cause=%d req_seq=%" PRIu32 " rsp_seq=%" PRIu32 " rounds=%" PRIu32 "\n",
               (int)cause, seq, rd(&ulp_rsp_seq), s_deep_rounds);
        print_regs("deep_wake");
        if (cause == ESP_SLEEP_WAKEUP_COCPU || cause == ESP_SLEEP_WAKEUP_ULP) {
            s_deep_wakes++;
            fill_pages();
            if (seq != 0u && seq != rd(&ulp_rsp_seq)) {
                serve(seq);
            }
        }
        s_deep_rounds++;
        printf("DEEP ROUND %" PRIu32 " ulp_wakes=%" PRIu32 " req_seq=%" PRIu32
               " rsp_seq=%" PRIu32 "\n",
               s_deep_rounds, s_deep_wakes, rd(&ulp_req_seq), rd(&ulp_rsp_seq));
        fflush(stdout);
        if (s_deep_rounds < DEEP_ROUNDS) {
            enter_deep(0);
        }
        ulp_riscv_timer_stop();
        printf("P23 done deep_wakes=%" PRIu32 "/%" PRIu32 " (deep path)\n",
               s_deep_wakes, (uint32_t)DEEP_ROUNDS);
        fflush(stdout);
        return;
    }

    fill_pages();
    s_doorbell = xSemaphoreCreateBinary();
    /* Path 1/2/3 need the RTC COCPU interrupt, not a GPIO: ulp_riscv_isr_register chains
     * the handler onto the RTC ISR and sets RTC_CNTL_INT_ENA_REG itself. */
    /* GUARDRAIL: register the SW (COCPU) mask only.  ULP_RISCV_TRAP_INT is not what
     * ulp_riscv_wakeup_main_processor() raises, and on this chip its status bit latches on
     * its own — adding it costs a whole run to a storm.  Clear stale status first. */
    REG_WRITE(RTC_CNTL_INT_CLR_REG, UINT32_MAX);
    ESP_ERROR_CHECK(ulp_riscv_isr_register(ulp_sw_isr, NULL, ULP_RISCV_SW_INT));
    printf("P23 SETUP isr=rtc_cocpu ena=0x%08" PRIx32 "\n", REG_READ(RTC_CNTL_INT_ENA_REG));
    fflush(stdout);

    xTaskCreatePinnedToCore(serve_task, "page_server", 4096, NULL, 20, NULL, 1);
    esp_task_wdt_reset();
    wait_for_go();

    run_awake(0, "A_poll");                  /* control */
    run_awake(1, "B_isr_blocked");           /* path 1 */
    run_light_sleep();                       /* path 2 */

    s_finished = 1;
    vTaskDelay(pdMS_TO_TICKS(20));
    enter_deep(1);                           /* path 3: last, it reboots the chip */
}
