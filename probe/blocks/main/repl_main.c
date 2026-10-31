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
#include "esp_system.h"
#include "soc/soc.h"
#include "ulp_riscv.h"
#include "ulp_main.h"

#define CONSOLE_UART  UART_NUM_0
#define CONSOLE_BAUD  115200

static const char *TAG = "repl";

/* The generated header declares these as uint32_t; the ring members are bytes inside them, so the
 * address is what matters. Same trick P22 proved with mem[]. */
#define CMD_BYTES  ((volatile uint8_t *)&ulp_repl_cmd)
#define OUT_BYTES  ((volatile uint8_t *)&ulp_repl_out)
/* GUARDRAIL: must equal the ULP's CMD_SIZE/OUT_SIZE. They lived in two files with no link between
 * them; when the ULP rings shrank to 64/128 and this stayed at 128/256, the host wrote past the end of
 * repl_cmd[] into repl_out[] and the REPL replayed old characters. The boot assert below is the link. */
/* GUARDRAIL: must equal the ULP's EXP_RINGS sizes (RING_CMD 32, RING_OUT 64). The boot assert below
 * refused to run when these disagreed — measured: "FATAL: ring size mismatch — ULP cmd=32 out=64, host
 * cmd=64 out=128". That is the assert from E-056 doing exactly its job; without it the host would have
 * written past repl_cmd[] into repl_out[] and the console would have replayed stale characters.
 * Note the trade: a 32 B command ring is one wake of typing (32 B drained per wake). */
#define CMD_SIZE   32u
#define OUT_SIZE   64u
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

        /* GUARDRAIL: vTaskDelay(pdMS_TO_TICKS(2)) is vTaskDelay(0) at the default 100 Hz tick — the pump
         * then spins at priority 10 and starves app_main (priority 1) forever, so tasks created after it
         * never exist. Measured: the block server never started and app_main's next printf never ran.
         * One tick (10 ms) guarantees a yield; the ULP drains on its own schedule anyway. */
        vTaskDelay(1);
    }
}

/* ---- EXP_BLK: the byte server ---------------------------------------------------------------
 * The ULP owns the block protocol (blk_xfer): it writes blk/op/checksum into its own mailbox, raises
 * repl_blk_req and spins. This core answers. It reads the ULP's mailbox and block buffer through
 * ADDRESSES the ULP publishes, because both are static and never exported by the map generator.
 *
 * GUARDRAIL: the backend here is a RAM file, not flash. That is deliberate for the first board test —
 * it proves the handshake, the checksum and the buffer copy end to end, and keeps a flash write out of
 * the first run. Replacing file[] with a partition read is a separate, additive step.
 * GUARDRAIL: the status write must be LAST and must be a single aligned u32 store; the ULP polls it in a
 * tight loop and treats non-zero as "answered". Writing the data after the status would let the ULP read
 * a half-copied buffer with a valid status.
 */
#define BLK_N     8
#define BLK_SZ    256
static uint8_t blkfile[BLK_N][BLK_SZ];

/* GUARDRAIL: the ULP ELF is linked at address 0, so every address it publishes (mem base, mailbox) is an
 * OFFSET into RTC slow memory, not an absolute pointer. Dereferencing the offset directly panics:
 * "Guru Meditation … LoadProhibited … EXCVADDR 0x00001e68", which is the mailbox offset. Add the base. */
#define ULP_RAM_BASE ((uint32_t)SOC_RTC_DATA_LOW)   /* 0x5000_0000 on this part */
_Static_assert(SOC_RTC_DATA_HIGH - SOC_RTC_DATA_LOW >= 8192, "ULP RAM window must hold the image");

static uint32_t blk_sum(const uint8_t *p, int n)
{
    uint32_t s = 0; int i;
    for (i = 0; i < n; i++) s = (s + p[i]) & 0xffffu;
    return s;
}

static void block_task(void *arg)
{
    (void)arg;
    /* GUARDRAIL: the first board run answered ERR_NO_SERVER on the ULP side while this task looked
     * healthy, so the server now reports what it can actually see: the published addresses once, and a
     * count of requests. Without this the only symptom is a timeout on the other core. */
    /* GUARDRAIL: this diagnostics block interleaves with the operator's own echo and turns a clean
     * transcript into noise. Keep it behind a flag, OFF by default: the console is the product. */
#if defined(BLK_DEBUG)
    printf("blksrv: addr mem=0x%08x blkoff=%u mb=0x%08x\n",
           (unsigned)ulp_repl_mem_addr, (unsigned)ulp_repl_blk_off, (unsigned)ulp_repl_mb_addr);
    fflush(stdout);
#endif
#if defined(BLK_DEBUG)
    uint32_t seen = 0;
#endif
    for (;;) {
        if (ulp_repl_blk_req) {
#if defined(BLK_DEBUG)
            if (seen < 3) {
                volatile uint32_t *dbg = (volatile uint32_t *)(ULP_RAM_BASE + ulp_repl_mb_addr);
                printf("blksrv: req #%u blk=%u op=%u sum=%u\n", (unsigned)++seen,
                       (unsigned)dbg[0], (unsigned)dbg[1], (unsigned)dbg[3]);
                fflush(stdout);
            }
            seen++;
#endif
            volatile uint32_t *mb = (volatile uint32_t *)(ULP_RAM_BASE + ulp_repl_mb_addr);
            volatile uint8_t  *buf = (volatile uint8_t *)(ULP_RAM_BASE + ulp_repl_mem_addr + ulp_repl_blk_off);
            uint32_t blk = mb[0], op = mb[1];
            if (blk >= BLK_N) {
                mb[2] = 2;                       /* nack: no such block */
            } else if (op == 0u) {               /* READ */
                uint32_t s = 0; int i;
                for (i = 0; i < BLK_SZ; i++) { buf[i] = blkfile[blk][i]; s += blkfile[blk][i]; }
                /* GUARDRAIL: a checksum disagreement between the two cores has three possible owners —
                 * the store, the copy, or the check — and the board transcript cannot tell them apart.
                 * Print what this core actually has AFTER the copy, so the ULP's complaint has a number
                 * to compare against instead of being an argument about who is wrong. */
#if defined(BLK_DEBUG)
                if (seen <= 6) {
                    printf("blksrv: READ blk=%u file=%u,%u buf=%u,%u sum=%u\n", (unsigned)blk,
                           (unsigned)blkfile[blk][0], (unsigned)blkfile[blk][1],
                           (unsigned)buf[0], (unsigned)buf[1], (unsigned)(s & 0xffffu));
                    fflush(stdout);
                }
#endif
                mb[3] = s & 0xffffu;
                mb[2] = 1u;
            } else {                             /* WRITE */
                uint32_t s = 0; int i;
                for (i = 0; i < BLK_SZ; i++) s += buf[i];
                if ((s & 0xffffu) != mb[3]) {
                    mb[2] = 0xFFFFFFFCu;         /* nack: checksum mismatch (BK_CRC) */
                } else {
                    for (i = 0; i < BLK_SZ; i++) blkfile[blk][i] = buf[i];
                    mb[2] = 1u;
                }
            }
        }
        vTaskDelay(1);                            /* 1 ms: the ULP's poll is bounded, so keep this short */
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

    /* Loud before anything else: if these disagree, every byte the user types is written to the wrong
     * place in the coprocessor's memory and the symptom looks like Forth corruption, not like a bug in
     * a size constant. Refuse to run the bridge at all rather than serve a broken console. */
    if (ulp_repl_cmd_bytes != CMD_SIZE || ulp_repl_out_bytes != OUT_SIZE) {
        printf("FATAL: ring size mismatch — ULP cmd=%u out=%u, host cmd=%u out=%u\n",
               (unsigned)ulp_repl_cmd_bytes, (unsigned)ulp_repl_out_bytes,
               (unsigned)CMD_SIZE, (unsigned)OUT_SIZE);
        fflush(stdout);
        for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
    }
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

    printf("app_main: creating tasks (heap %u)\n", (unsigned)esp_get_free_heap_size());
    fflush(stdout);
    /* GUARDRAIL: create the byte server first. A higher-priority task that never yields can starve this
     * one, and then anything created after it silently never exists (measured: block_task absent, only a
     * timeout on the other core as evidence). Order is part of the correctness here. */
    BaseType_t ok = xTaskCreate(block_task, "blocksrv", 2048, NULL, 12, NULL);
    printf("app_main: blocksrv %s (heap %u)\n", ok == pdPASS ? "up" : "FAILED",
           (unsigned)esp_get_free_heap_size());
    fflush(stdout);
    xTaskCreate(console_task, "console", 4096, NULL, 10, NULL);
    /* GUARDRAIL: check the return. The first version ignored it and the server task silently never
     * existed — the only symptom was ERR_NO_SERVER on the other core, which looks like a protocol bug.
     * A task that does not start must say so. */

}
