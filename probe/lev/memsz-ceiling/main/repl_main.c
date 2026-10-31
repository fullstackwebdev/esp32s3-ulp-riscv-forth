/* repl_main.c — the HP side: a dumb byte pump between UART0 and the ULP's two rings.
 *
 * It does not parse Forth, does not queue commands, and does not decide anything. That is the whole
 * point of the split: the interpreter is on the ULP, this core moves bytes and nothing else (R6).
 *
 * You talk to it with any terminal:  picocom -b 115200 /dev/ttyACM1
 *
 * GUARDRAIL: the ULP is armed only after the banner is printed and the port is up. A board that is
 * armed before it can talk is a board that wedges silently — the P06 lesson, which cost a physical
 * reset and the firmware that was on the chip.
 *
 * GUARDRAIL: one writer per ring index. This task writes cmd_head and out_tail; the ULP writes
 * cmd_tail and out_head. Both are u32-aligned, so no lock is needed for the counters, and adding one
 * would be the only place a deadlock could live.
 */
#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "ulp_riscv.h"
#include "ulp_main.h"

#define CONSOLE_UART  UART_NUM_0
#define CONSOLE_BAUD  115200

static const char *TAG = "repl";

/* The generated header declares these as uint32_t; the ring members are bytes inside them, so the
 * address is what matters. Same trick P22 proved with mem[]. */
#define CMD_BYTES  ((volatile uint8_t *)&ulp_repl_cmd)
#define OUT_BYTES  ((volatile uint8_t *)&ulp_repl_out)
#define CMD_SIZE   128u
#define OUT_SIZE   256u
#define CMD_MASK   (CMD_SIZE - 1u)
#define OUT_MASK   (OUT_SIZE - 1u)

extern const uint8_t bin_start[] asm("_binary_ulp_main_bin_start");
extern const uint8_t bin_end[]   asm("_binary_ulp_main_bin_end");

static void console_task(void *arg)
{
    (void)arg;
    uint8_t buf[64];

    for (;;) {
        /* UART -> cmd ring. Stop when the ring is full; the ULP drains 32 bytes per wake, and at a
         * 1 000-tick period that is ~3 ms, so the ring cannot back up under human typing. */
        int n = uart_read_bytes(CONSOLE_UART, buf, sizeof buf, 0);
        for (int i = 0; i < n; i++) {
            uint32_t h = ulp_repl_cmd_head;
            uint32_t t = ulp_repl_cmd_tail;
            if ((h - t) >= CMD_SIZE) break;          /* full: let the ULP catch up, drop nothing */
            CMD_BYTES[h & CMD_MASK] = buf[i];
            ulp_repl_cmd_head = h + 1u;
        }

        /* out ring -> UART */
        uint32_t oh = ulp_repl_out_head;
        uint32_t ot = ulp_repl_out_tail;
        if (oh != ot) {
            uint8_t out[64];
            uint32_t k = 0;
            while (ot != oh && k < sizeof out) {
                out[k++] = OUT_BYTES[ot & OUT_MASK];
                ot++;
            }
            ulp_repl_out_tail = ot;
            uart_write_bytes(CONSOLE_UART, (const char *)out, k);
        }

        vTaskDelay(pdMS_TO_TICKS(2));
    }
}

void app_main(void)
{
    /* Watchdog first (P06): a hung bridge takes the console *and* the flashing port with it. */
    esp_task_wdt_config_t wdt = { .timeout_ms = 5000, .idle_core_mask = 0, .trigger_panic = true };
    esp_task_wdt_reconfigure(&wdt);

    uart_config_t cfg = {
        .baud_rate = CONSOLE_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(CONSOLE_UART, 1024, 1024, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(CONSOLE_UART, &cfg));

    printf("\nboot: ulp forth bridge, %u B image\n", (unsigned)(bin_end - bin_start));
    printf("type Forth at the prompt; 'picocom -b %d /dev/ttyACM1'\n", CONSOLE_BAUD);
    fflush(stdout);

    ESP_ERROR_CHECK(ulp_riscv_load_binary(bin_start, (size_t)(bin_end - bin_start)));
    /* 1 000 ticks at the measured 6.46 us/tick = 6 460 us. The API takes microseconds. */
    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, 6460));
    ESP_ERROR_CHECK(ulp_riscv_run());
    ESP_LOGI(TAG, "ulp armed");

    /* GUARDRAIL: report the ULP's own wake counter before handing over. Without it, a silent console is
     * ambiguous — "the coprocessor never started" and "the coprocessor started and did nothing" look
     * identical from the port, and the counterfactual test in P41 is worthless if it cannot tell them
     * apart. This line is the proof that the ULP is alive; its absence is a different failure. */
    vTaskDelay(pdMS_TO_TICKS(500));
    printf("ulp woke %u times\n", (unsigned)ulp_repl_wake_count);
    fflush(stdout);

    xTaskCreate(console_task, "console", 4096, NULL, 10, NULL);
}
