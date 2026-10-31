/* p39_main.c — P39: the HP half. Load our interpreter into the ULP, run it at a period, print what
 * came back over UART0 (/dev/ttyACM1, 115200).
 *
 * Staged on purpose, per the board rules: watchdog first, then UART/banner, then the experiment only
 * after 'g' arrives on the console. If the board goes silent, the last line printed says which step
 * did it.
 *
 * The three failure modes the probe asks to distinguish, and what each looks like here:
 *   trap        — p39_wake_count 1..N then frozen, RTC_CNTL_COCPU_TRAP_INT_RAW set, stage published
 *                 but no output bytes; the ip/status are printed from the ULP's own stamps.
 *   never runs  — p39_wake_count == 0 and stage == 0 after the window.
 *   wrong answer— stage 3 with the raw bytes != "20", or stage 0xF1/0xE* with the prelude stop point.
 */
#include <stdio.h>
#include <inttypes.h>

#include "esp_timer.h"
#include "esp_sleep.h"
#include "esp_task_wdt.h"
#include "driver/uart.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "ulp_riscv.h"
#include "ulp_main.h"
#include "soc/rtc_cntl_reg.h"

extern const uint8_t ulp_main_bin_start[] asm("_binary_ulp_main_bin_start");
extern const uint8_t ulp_main_bin_end[] asm("_binary_ulp_main_bin_end");

/* GUARDRAIL: ulp_* are linker-PROVIDEd absolute RTC-slow-memory addresses; reading them directly lets
 * the optimiser cache the first snapshot, and a whole P05 phase once reported an earlier wake's
 * counters. Always go through this accessor. */
static inline uint32_t rd(const volatile uint32_t *p) { return *(volatile const uint32_t *)p; }

/* P05: 154.9 kHz RTC slow clock, 6.46 us per tick, 122.6 CPU cycles per tick. The probe's period is
 * 1000 ticks; ulp_set_wakeup_period() takes MICROSECONDS and converts with the calibrated slow clock,
 * so the number below is 1000 x 6.46 us. Reported both ways in the log. */
#define TICK_US 6.46
#define PERIOD_TICKS 1000u
#define PERIOD_US ((uint32_t)(PERIOD_TICKS * TICK_US))   /* 6460 us */

static void wdt_feed(void) { esp_task_wdt_reset(); }

/* bounded window: an esp_timer wall-clock check plus a feed on every step (P05's window once
 * collapsed onto its iteration cap because vTaskDelay(pdMS_TO_TICKS(1)) is vTaskDelay(0) at 100 Hz). */
static void wait_ms(uint32_t ms)
{
    int64_t t0 = esp_timer_get_time();
    while (esp_timer_get_time() - t0 < (int64_t)ms * 1000) {
        esp_rom_delay_us(1000);
        wdt_feed();
    }
}

static uint32_t out_bytes(void)
{
    uint32_t w = rd(&ulp_p39_out_word);
    return w;
}

static void stage_gate(void)
{
    printf("P39 READY stage=console — send 'g' on UART0 (115200) to arm the ULP\n");
    fflush(stdout);
    int got = 0;
    for (int i = 0; i < 400 && !got; i++) {          /* 400 x 50 ms = 20 s cap */
        uint8_t c = 0;
        if (uart_read_bytes(UART_NUM_0, &c, 1, pdMS_TO_TICKS(50)) == 1 && (c == 'g' || c == 'G')) got = 1;
        wdt_feed();
    }
    printf("P39 GO gate=%s\n", got ? "console" : "timeout");
    fflush(stdout);
}

void app_main(void)
{
    /* GUARDRAIL: the task watchdog goes up BEFORE UART init and before any ULP call — a hang in our
     * own code would otherwise eat the console and leave no way to tell "chip wedged" from "app
     * spinning" (the P06 first attempt lost hours to exactly that). */
    esp_task_wdt_config_t wdt_cfg = { .timeout_ms = 12000, .idle_core_mask = 0, .trigger_panic = true };
    esp_err_t wdt_err = esp_task_wdt_init(&wdt_cfg);
    if (wdt_err != ESP_OK) {
        wdt_err = esp_task_wdt_reconfigure(&wdt_cfg);   /* IDF already initialised it at startup */
    }
    esp_task_wdt_add(NULL);
    esp_task_wdt_reset();
    printf("P39 BOOT stage=wdt wdt_init=%d\n", (int)wdt_err);
    fflush(stdout);

    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0));
    wdt_feed();

    size_t bin_len = (size_t)(ulp_main_bin_end - ulp_main_bin_start);
    printf("P39 BOOT stage=image bin=%u bytes (stub floor 142 B, so engine+prelude+harness)\n",
           (unsigned)bin_len);
    fflush(stdout);

    stage_gate();

    /* Never write COCPU_* and never touch the ULP's variables: the image is loaded, similar to P06's
     * reload(), with the timer stopped first so no wake can be in flight while the binary is copied. */
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(20));
    wdt_feed();

    esp_err_t lerr = ulp_riscv_load_binary(ulp_main_bin_start, bin_len);
    printf("P39 LOAD rc=%d period_ticks=%" PRIu32 " period_us=%" PRIu32 "\n",
           (int)lerr, (uint32_t)PERIOD_TICKS, PERIOD_US);   /* PRIu32 is "lu" on xtensa: an unsigned int literal trips -Werror=format */
    fflush(stdout);
    if (lerr != ESP_OK) { printf("P39 FAIL mode=load rc=%d\n", (int)lerr); return; }

    printf("P39 BEFORE wake_count=%" PRIu32 " stage=%" PRIu32 " done=%" PRIu32 "\n",
           rd(&ulp_p39_wake_count), rd(&ulp_p39_stage), rd(&ulp_p39_done));
    fflush(stdout);

    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, PERIOD_US));
    ESP_ERROR_CHECK(ulp_riscv_run());
    wdt_feed();

    wait_ms(400);
    ulp_riscv_timer_stop();
    vTaskDelay(pdMS_TO_TICKS(50));    /* let an in-flight wake retire */
    wdt_feed();

    uint32_t wakes = rd(&ulp_p39_wake_count);
    uint32_t st    = rd(&ulp_p39_stage);
    uint32_t stage_first = st;
    uint32_t w2    = rd(&ulp_p39_wake_count);
    /* GUARDRAIL: there is no RTC_CNTL_COCPU_INT_RAW_REG on the S3 — the ULP core's trap interrupt is
     * bit 17 of the shared RTC_CNTL_INT_RAW register (RTC_CNTL_COCPU_TRAP_INT_RAW). Reading a
     * register the SOC header does not define is a build stop, not a probe result. */
    uint32_t trap_raw = REG_READ(RTC_CNTL_INT_RAW_REG);
    int trap = (trap_raw & RTC_CNTL_COCPU_TRAP_INT_RAW) ? 1 : 0;
    uint32_t ctrl  = REG_READ(RTC_CNTL_COCPU_CTRL_REG);
    uint32_t cause = REG_READ(RTC_CNTL_SLP_WAKEUP_CAUSE_REG);
    uint32_t oword = out_bytes();
    uint32_t olen  = rd(&ulp_p39_out_len);

    printf("P39 RESULT wake_count=%" PRIu32 " stage=%" PRIu32 " done=%" PRIu32
           " here_boot=%" PRIu32 " here_prelude=%" PRIu32 "\n",
           wakes, stage_first, rd(&ulp_p39_done), rd(&ulp_p39_here_boot), rd(&ulp_p39_here_prelude));
    /* GUARDRAIL: cast every byte to unsigned — the shifts promote to long, and -Werror=format killed
     * a build that had already linked the ULP image, i.e. on a pure printf detail. */
    printf("P39 OUT len=%" PRIu32 " word=0x%08" PRIX32 " byte0=%02X byte1=%02X byte2=%02X byte3=%02X\n",
           olen, oword, (unsigned)(oword & 0xff), (unsigned)((oword >> 8) & 0xff),
           (unsigned)((oword >> 16) & 0xff), (unsigned)((oword >> 24) & 0xff));
    printf("P39 OUT as-string=\"%c%c%c%c\"\n",
           (int)(oword & 0xff), (int)((oword >> 8) & 0xff),
           (int)((oword >> 16) & 0xff), (int)((oword >> 24) & 0xff));
    printf("P39 STACK sp=%" PRIu32 " rsp=%" PRIu32 " errf=%" PRIu32 "\n",
           rd(&ulp_p39_sp), rd(&ulp_p39_rsp), rd(&ulp_p39_errf));
    printf("P39 CYC rdcycle_at_wake_start=%" PRIu32 "\n", rd(&ulp_p39_cyc_start));
    printf("P39 REG trap_int_raw=0x%08" PRIX32 " cocpu_ctrl=0x%08" PRIX32
           " slp_wakeup_cause=0x%08" PRIX32 " wake_count_second_read=%" PRIu32 "\n",
           trap_raw, ctrl, cause, w2);

    /* One explicit verdict per failure mode, so the log cannot be read two ways. */
    int is20 = (olen == 2) && ((oword & 0xffff) == ((uint32_t)('2') | ((uint32_t)('0') << 8)));
    if (wakes == 0) {
        printf("P39 FAIL mode=never-ran wake_count=0 stage=%" PRIu32 " bin=%u\n",
               stage_first, (unsigned)bin_len);
    } else if (trap) {
        printf("P39 FAIL mode=trap wake_count=%" PRIu32 " stage=%" PRIu32 " here=%" PRIu32
               " sp=%" PRIu32 " rsp=%" PRIu32 "\n",
               wakes, stage_first, rd(&ulp_p39_here_prelude), rd(&ulp_p39_sp), rd(&ulp_p39_rsp));
    } else if (wakes > 0 && w2 == wakes && st == 1u && rd(&ulp_p39_done) == 0u) {
        printf("P39 FAIL mode=stalled-in-prelude wake_count=%" PRIu32 " (same at re-read)\n", wakes);
    } else if (is20) {
        printf("P39 PASS answer=20\n");
    } else {
        printf("P39 FAIL mode=wrong-answer len=%" PRIu32 " word=0x%08" PRIX32 " stage=%" PRIu32 "\n",
               olen, oword, stage_first);
    }

    /* Leave a known state: timer stopped, ULP not armed, period source untouched. */
    uint32_t timer_reg = REG_READ(RTC_CNTL_ULP_CP_TIMER_REG);
    printf("P39 STATE ulp_cp_timer=0x%08" PRIX32 " slp_timer_en=%d (0 = disarmed)\n",
           timer_reg, (timer_reg & RTC_CNTL_ULP_CP_SLP_TIMER_EN) ? 1 : 0);
    printf("P39 done\n");
    fflush(stdout);
}
