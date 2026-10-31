/* P16 — HP-side byte server: what does one 512 B page fetch cost the ULP?
 *
 * Staged so a wedge is attributable and bounded: watchdog first, then UART, then a banner,
 * then the experiment only after 'g' arrives on UART0 (115200, /dev/ttyACM1).
 *
 * The server is deliberately dumb (R6): a single FreeRTOS task that watches the request
 * slot in RTC slow memory, bounds-checks the address, copies 512 B, checksums it and
 * answers with seq + status + checksum.  No Forth, no parsing.
 *
 * Phases, all in one 'g' run:
 *   A  HP awake, busy-polling the request slot          (tests 1, 4)
 *   B  HP awake, blocked on the ULP's GPIO doorbell     (test 2)
 *   F1 server stopped        -> the ULP must name a timeout, not hang, not zero-fill
 *   F2 corrupted checksum    -> the ULP must reject the page
 *   F3 out-of-range address  -> the ULP must see a status, not a silent zero page
 *   F4 two requests in flight-> does the first answer get swallowed / carry the wrong page?
 *   C  HP in deep sleep, woken by the ULP, booting, servicing — see C-STATUS line.
 */
#include <stdio.h>
#include <string.h>
#include <inttypes.h>

#include "esp_timer.h"
#include "esp_rom_sys.h"
#include "esp_attr.h"
#include "esp_task_wdt.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "driver/rtc_io.h"
#include "ulp_riscv.h"
#include "ulp_main.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

extern const uint8_t ulp_main_bin_start[] asm("_binary_ulp_main_bin_start");
extern const uint8_t ulp_main_bin_end[] asm("_binary_ulp_main_bin_end");

/* ulp_* are linker-PROVIDEd absolute RTC-slow-memory addresses: read them through a
 * volatile pointer or the optimiser caches the first snapshot.
 * GUARDRAIL: reading ulp_<name> without volatile made a whole P05 phase report counters of
 * an earlier wake — always go through this accessor. */
static inline uint32_t rd(const uint32_t *p) { return *(volatile const uint32_t *)p; }
static inline void wr(uint32_t *p, uint32_t v) { *(volatile uint32_t *)p = v; __sync_synchronize(); }

/* P05: 122.6 ULP cycles per RTC tick, 6.46 us per tick (=> 19.0 MHz ULP core). */
#define CYCLES_PER_TICK_X10 1226
#define TICKS_PER_SEC       154900u

#define PAGE_BYTES   512u
#define WINDOW_BYTES 2048u            /* P19: frames fixed at 4 x 512 */
#define N_ITER       200u

/* GUARDRAIL: GPIO19/20 are native USB D-/D+ — driving them killed the USB-JTAG peripheral
 * and forced a hands-on EN press (P06).  Doorbell is RTC GPIO4: not USB, not strapping,
 * not UART0, not flash/PSRAM. */
#define DOORBELL_GPIO 4

static uint8_t s_pages[4][PAGE_BYTES];
static SemaphoreHandle_t s_doorbell;
static volatile int s_blocked_mode;
/* Fault injection is HP-local state: the ULP never reads it, and a ULP .bss word that the
 * ULP does not reference is dropped by --gc-sections, so it never appears in ulp_main.h
 * (build error: 'ulp_fault_inject undeclared'). */
static volatile uint32_t s_fault_inject;
static volatile uint32_t s_doorbell_isr;
static volatile int s_finished;

/* ---- failure-mode states, readable from the log alone ---- */
#define ST_OK 0
#define ST_TIMEOUT 1
#define ST_BADCHK 2
#define ST_RANGE 3
#define ST_STALE 4
#define ST_DUAL 5
static const char *st_name(uint32_t s)
{
    switch (s) {
    case ST_OK:      return "OK";
    case ST_TIMEOUT: return "TIMEOUT_NO_ANSWER";
    case ST_BADCHK:  return "CHECKSUM_REJECTED";
    case ST_RANGE:   return "RANGE_REJECTED";
    case ST_STALE:   return "WRONG_PAGE";
    case ST_DUAL:    return "TWO_IN_FLIGHT_CORRUPT";
    default:         return "UNDEFINED";
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

static void fill_pages(void)
{
    for (uint32_t pg = 0; pg < 4; pg++) {
        /* page index in the first word (the ULP's stale-page marker), then a
         * position-dependent pattern so a partially copied page cannot pass the
         * checksum by accident. */
        for (uint32_t i = 0; i < PAGE_BYTES; i++) {
            s_pages[pg][i] = (uint8_t)((pg * 37u) + i * 7u + 1u);
        }
        uint32_t tag = pg;                       /* little-endian page index in word 0 */
        memcpy(&s_pages[pg][0], &tag, 4);
    }
}

/* One service: bounds check, copy 512 B, checksum, answer.  Anything else here would be
 * logic on the server, which R6 forbids. */
static void serve(uint32_t seq)
{
    uint32_t addr = rd(&ulp_req_addr);
    if (addr > WINDOW_BYTES - PAGE_BYTES) {
        wr(&ulp_rsp_status, 2);                  /* rejected: no page copied */
        wr(&ulp_rsp_seq, seq);
        return;
    }
    const uint8_t *src = s_pages[(addr >> 9) & 3u];
    /* GUARDRAIL: the mapgen symbol is the *address* of the ULP variable, so `(void *)ulp_page`
     * is the uint32 stored at that address (0 at boot) and `memcpy(..., 512)` faults with
     * StoreProhibited/EXCVADDR=0.  Always take `&ulp_<name>`. */
    memcpy((void *)&ulp_page, src, PAGE_BYTES);
    uint32_t c = chk512((const uint8_t *)&ulp_page);
    if (s_fault_inject & 1u) {
        c ^= 0xDEADBEEFu;                        /* deliberate bad CRC */
    }
    wr(&ulp_rsp_chk, c);
    wr(&ulp_rsp_status, 1);
    wr(&ulp_rsp_seq, seq);
}

static void serve_task(void *arg)
{
    uint32_t last = 0;
    for (;;) {
        uint32_t seq;
        /* Leaving a spinning server task behind after the run is not a known state: the
         * core-1 idle task would never run again.  The experiment ends by parking it. */
        if (s_finished) {
            printf("P16 SERVER stopped\n");
            fflush(stdout);
            vTaskDelete(NULL);
        }
        if (s_fault_inject & 2u) {               /* server stopped */
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }
        if (s_blocked_mode) {
            /* GUARDRAIL: bounded take, never portMAX_DELAY — a missed doorbell must show up
             * as a named timeout in the log, not as a task that hangs the phase and eats
             * the console (the P06 wedge cost hours of guessing). */
            if (xSemaphoreTake(s_doorbell, pdMS_TO_TICKS(400)) != pdTRUE) {
                continue;
            }
            seq = rd(&ulp_req_seq);
            if (seq == 0u || seq == last) {
                continue;
            }
        } else {
            seq = rd(&ulp_req_seq);
            if (seq == 0u || seq == last) {
                continue;
            }
        }
        last = seq;
        serve(seq);
    }
}

static void IRAM_ATTR doorbell_isr(void *arg)
{
    BaseType_t hp = pdFALSE;
    s_doorbell_isr++;
    xSemaphoreGiveFromISR(s_doorbell, &hp);
    if (hp) {
        portYIELD_FROM_ISR();
    }
}

/* Reload the ULP image (which re-initialises its .bss) and stage one pass.
 * GUARDRAIL: the HP must never write a word the ULP may be reading while the ULP is live
 * (P06 wedged the board that way).  Staging happens only after ulp_riscv_timer_stop() and a
 * settle delay, never during a pass. */
static void stage(uint32_t mode, uint32_t fcase, uint32_t fault_inject, uint32_t n_iter)
{
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(50));
    esp_task_wdt_reset();
    ESP_ERROR_CHECK(ulp_riscv_load_binary(ulp_main_bin_start,
                                          (size_t)(ulp_main_bin_end - ulp_main_bin_start)));
    wr(&ulp_mode, mode);
    wr(&ulp_fcase, fcase);
    wr(&ulp_n_iter, n_iter);
    wr(&ulp_req_seq, 0);
    wr(&ulp_req_addr, 0);
    wr(&ulp_rsp_seq, 0);
    wr(&ulp_rsp_status, 0);
    wr(&ulp_rsp_chk, 0);
    s_fault_inject = fault_inject;
    wr(&ulp_phase_done, 0);
    wr(&ulp_f_seq_seen, 0xFFFFFFFFu);
    wr(&ulp_f_marker, 0xFFFFFFFFu);
    wr(&ulp_f_status, 0xFFFFFFFFu);
}

static int run_pass(uint32_t timeout_ms)
{
    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, 1000000));
    ESP_ERROR_CHECK(ulp_riscv_run());
    int64_t t0 = esp_timer_get_time();
    int done = 0;
    while (esp_timer_get_time() - t0 < (int64_t)timeout_ms * 1000) {
        esp_task_wdt_reset();
        if (rd(&ulp_phase_done) == 1u) {
            done = 1;
            break;
        }
        esp_rom_delay_us(200);
    }
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(50));
    esp_task_wdt_reset();
    return done;
}

static int cmp_u32(const void *a, const void *b)
{
    uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;
    return (x > y) - (x < y);
}

static void print_stats(const char *tag, int done, uint32_t elapsed_ms)
{
    static uint32_t v[N_ITER];
    uint32_t n = 0, nok = 0;
    for (uint32_t i = 0; i < N_ITER; i++) {
        uint32_t d = ((const uint32_t *)&ulp_deltas)[i];
        if (d != 0u) {
            v[n++] = d;
            if (((const uint8_t *)&ulp_statii)[i] == ST_OK) {
                nok++;
            }
        }
    }
    if (n == 0) {
        printf("STATS %s n=0 pass_done=%d\n", tag, done);
        return;
    }
    qsort(v, n, sizeof(uint32_t), cmp_u32);
    uint32_t mn = v[0], md = v[n / 2], p95 = v[(n * 95u) / 100u], mx = v[n - 1];
    uint32_t sum = 0;
    for (uint32_t i = 0; i < n; i++) {
        sum += v[i];
    }
    uint32_t mean = sum / n;
    printf("STATS %s n=%" PRIu32 " ok=%" PRIu32 " pass_done=%d pass_ms=%" PRIu32
           " min_cyc=%" PRIu32 " med_cyc=%" PRIu32 " p95_cyc=%" PRIu32
           " max_cyc=%" PRIu32 " mean_cyc=%" PRIu32 "\n",
           tag, n, nok, done, elapsed_ms, mn, md, p95, mx, mean);
    /* ticks = cycles / 122.6 ; us = ticks * 6.46  (both x1000 for three decimals) */
    printf("TICKS %s min=%" PRId64 " med=%" PRId64 " p95=%" PRId64 " max=%" PRId64
           " mean=%" PRId64 "\n",
           tag,
           (int64_t)mn * 10000 / CYCLES_PER_TICK_X10,
           (int64_t)md * 10000 / CYCLES_PER_TICK_X10,
           (int64_t)p95 * 10000 / CYCLES_PER_TICK_X10,
           (int64_t)mx * 10000 / CYCLES_PER_TICK_X10,
           (int64_t)mean * 10000 / CYCLES_PER_TICK_X10);
    printf("US %s min=%" PRId64 " med=%" PRId64 " p95=%" PRId64 " max=%" PRId64
           " mean=%" PRId64 "\n",
           tag,
           (int64_t)mn * 52692 / 1000000,
           (int64_t)md * 52692 / 1000000,
           (int64_t)p95 * 52692 / 1000000,
           (int64_t)mx * 52692 / 1000000,
           (int64_t)mean * 52692 / 1000000);
    printf("BYTES_PER_S %s median=%" PRId64 " best=%" PRId64 "\n",
           tag,
           (int64_t)PAGE_BYTES * 1000000 * 1000 / ((int64_t)md * 52692 / 1000),
           (int64_t)PAGE_BYTES * 1000000 * 1000 / ((int64_t)mn * 52692 / 1000));
}

static void fault_phase(uint32_t fcase, const char *tag)
{
    stage(2, fcase, (fcase == 1u) ? 2u : ((fcase == 2u) ? 1u : 0u), 1);
    int done = run_pass(3000);
    uint32_t seen = rd(&ulp_f_seq_seen);
    uint32_t marker = rd(&ulp_f_marker);
    uint32_t st = rd(&ulp_f_status);
    printf("FAULT %s case=%" PRIu32 " done=%d rsp_seq_seen=%" PRIu32
           " page_marker=%" PRIu32 " status=%" PRIu32 " name=%s\n",
           tag, fcase, done, seen, marker, st, st_name(st));
}

static void wait_for_go(void)
{
    printf("P16 READY stage=console — send 'g' on UART0 (115200) to start\n");
    fflush(stdout);
    int got = 0;
    for (int i = 0; i < 200 && !got; i++) {      /* 200 x 40 ms = 8 s cap */
        uint8_t c = 0;
        if (uart_read_bytes(UART_NUM_0, &c, 1, pdMS_TO_TICKS(40)) == 1 && (c == 'g' || c == 'G')) {
            got = 1;
        }
        esp_task_wdt_reset();
    }
    printf("P16 GO gate=%s\n", got ? "console" : "timeout");
    fflush(stdout);
}

void app_main(void)
{
    /* GUARDRAIL: the task watchdog goes up BEFORE UART and before any ULP call — in the
     * first P06 attempt a hang in our own code ate the console and left no way to tell
     * "chip wedged" from "app spinning".  12 s: covers a 200-iteration pass plus the
     * 3 s fault timeout. */
    esp_task_wdt_config_t wdt_cfg = {
        .timeout_ms = 12000,
        .idle_core_mask = 0,
        .trigger_panic = true,
    };
    esp_err_t wdt_err = esp_task_wdt_init(&wdt_cfg);
    if (wdt_err != ESP_OK) {
        wdt_err = esp_task_wdt_reconfigure(&wdt_cfg);
    }
    esp_task_wdt_add(NULL);
    esp_task_wdt_reset();

    printf("P16 BOOT stage=wdt wdt_init=%d window_bound=%s\n", (int)wdt_err, WINDOW_BYTES ? "2048" : "0");
    fflush(stdout);

    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0));
    esp_task_wdt_reset();

    fill_pages();
    s_doorbell = xSemaphoreCreateBinary();
    /* Doorbell: RTC GPIO4 as input with a HIGH-level interrupt; the ULP drives the pad from
     * RTCIO (it cannot touch the HP GPIO matrix). */
    gpio_config_t io = {
        .pin_bit_mask = 1ULL << DOORBELL_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = 0,
        .pull_down_en = 1,
        .intr_type = GPIO_INTR_HIGH_LEVEL,
    };
    gpio_config(&io);
    gpio_install_isr_service(0);
    gpio_isr_handler_add(DOORBELL_GPIO, doorbell_isr, NULL);
    /* GUARDRAIL: do NOT rtc_gpio_init() this pad.  With the pad muxed to its RTC function
     * (what rtc_gpio_init does) the digital GPIO input — the one this interrupt is attached
     * to — stops seeing the pad, so the ULP's RTCIO doorbell raised 200 edges that produced
     * isr_count=0 and every fetch timed out.  Leave the pad in its GPIO mux and let the ULP
     * write RTCIO; the digital level interrupt is what must fire. */
    rtc_gpio_deinit(DOORBELL_GPIO);
    printf("P16 SETUP doorbell=gpio%d pages=%s\n", DOORBELL_GPIO, "internal-ram");

    xTaskCreatePinnedToCore(serve_task, "page_server", 4096, NULL, 20, NULL, 1);
    esp_task_wdt_reset();
    wait_for_go();

    /* ---- A: HP awake, polling ---- */
    s_blocked_mode = 0;
    stage(0, 0, 0, N_ITER);
    int64_t tA = esp_timer_get_time();
    int doneA = run_pass(8000);
    print_stats("A_poll", doneA, (uint32_t)((esp_timer_get_time() - tA) / 1000));

    /* ---- B: HP awake, blocked on the ULP doorbell ---- */
    s_blocked_mode = 1;
    stage(1, 0, 0, N_ITER);
    int64_t tB = esp_timer_get_time();
    int doneB = run_pass(8000);
    print_stats("B_blocked", doneB, (uint32_t)((esp_timer_get_time() - tB) / 1000));
    printf("DOORBELL isr_count=%" PRIu32 "\n", s_doorbell_isr);
    s_blocked_mode = 0;

    /* ---- the four failure modes ---- */
    fault_phase(1, "server_stopped");
    fault_phase(2, "bad_crc");
    fault_phase(3, "out_of_range");
    fault_phase(4, "two_in_flight");

    /* GUARDRAIL: the deep-sleep configuration (C) is NOT run in this pass.  A fetch there
     * costs a whole HP boot, and each boot re-enters app_main; that needs its own staged
     * binary and its own 15-minute box, so it must never be smuggled into the same boot as
     * measurements that still have to be captured (P06 lost a run exactly that way). */
    printf("C-STATUS NOT_MEASURED reason=deep-sleep-wake-path-not-implemented-in-this-pass\n");

    s_finished = 1;
    printf("P16 done\n");
    fflush(stdout);
}
