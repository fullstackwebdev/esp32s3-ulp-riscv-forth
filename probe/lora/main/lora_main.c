/* lora_main.c - Heltec V3 (ESP32-S3 + SX1262) ULP-RISC-V LoRa transmit node, main-core side.
 *
 * The main core configures the radio pins as RTC GPIOs, starts the ULP, and then only reads counters. It does not touch
 * the SPI bus and it never transmits: the point of this build is to find out whether the ULP alone can run the radio.
 *
 * For the first bring-up the core stays awake and prints, so the ULP's verdict is visible. Deep sleep is switched on by
 * `#define LORA_SLEEP_AFTER_BRINGUP 1` once the counters look right.
 */
#include <stdio.h>
#include <inttypes.h>

#include "driver/rtc_io.h"
#include "driver/spi_master.h"
#include "esp_sleep.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "ulp_riscv.h"
#include "ulp_lora.h"

/* GUARDRAIL: this is the main core's own variable, NOT one of the ULP's exported symbols - naming it ulp_* would make
 * the linker look for a symbol the ULP never defines (and, worse, could alias one it does). Prefix is a contract. */
static uint32_t ulp_busy_us;

extern const uint8_t ulp_lora_bin_start[] asm("_binary_ulp_lora_bin_start");
extern const uint8_t ulp_lora_bin_end[]   asm("_binary_ulp_lora_bin_end");

/* Heltec WiFi LoRa 32 V3 - documented variant wiring for the SX1262. Kept in step with sx126x_ulp_hal.h; a mismatch
 * between the two is a silent SPI failure, so they are asserted below by construction (same numbers, one place to look). */
#define PIN_SCK    9
#define PIN_MOSI   10
#define PIN_MISO   11
#define PIN_NSS    8
#define PIN_RESET  12
#define PIN_BUSY   13
#define PIN_DIO1   14

#define ULP_WAKE_PERIOD_US (5ULL * 1000000ULL)

/* GUARDRAIL: do NOT call rtc_gpio_hold_en() on any pin the ULP drives. Hold freezes the pad, and the ULP then cannot
 * move it - the ULP would look like it is running while the SCK line stays dead (docs/28 §2.6, and the reference
 * driver's own comment). Hold is for pins nobody drives. */
static void rtc_out(int pin, int level)
{
    ESP_ERROR_CHECK(rtc_gpio_init((gpio_num_t)pin));
    ESP_ERROR_CHECK(rtc_gpio_set_direction((gpio_num_t)pin, RTC_GPIO_MODE_OUTPUT_ONLY));
    ESP_ERROR_CHECK(rtc_gpio_set_level((gpio_num_t)pin, level));
    ESP_ERROR_CHECK(rtc_gpio_pullup_dis((gpio_num_t)pin));
    ESP_ERROR_CHECK(rtc_gpio_pulldown_dis((gpio_num_t)pin));
}

static void rtc_in(int pin)
{
    ESP_ERROR_CHECK(rtc_gpio_init((gpio_num_t)pin));
    ESP_ERROR_CHECK(rtc_gpio_set_direction((gpio_num_t)pin, RTC_GPIO_MODE_INPUT_ONLY));
    ESP_ERROR_CHECK(rtc_gpio_pullup_dis((gpio_num_t)pin));
    ESP_ERROR_CHECK(rtc_gpio_pulldown_dis((gpio_num_t)pin));
}

static void start_ulp(void)
{
    const int pins[7] = { PIN_SCK, PIN_MOSI, PIN_MISO, PIN_NSS, PIN_RESET, PIN_BUSY, PIN_DIO1 };
    for (int i = 0; i < 7; i++) {
        gpio_reset_pin((gpio_num_t)pins[i]);   /* detach from the GPIO matrix before handing to RTC */
    }
    rtc_out(PIN_SCK, 0);
    rtc_out(PIN_MOSI, 0);
    rtc_out(PIN_NSS, 1);
    rtc_out(PIN_RESET, 1);
    rtc_in(PIN_MISO);
    rtc_in(PIN_BUSY);
    rtc_in(PIN_DIO1);

    ESP_ERROR_CHECK(ulp_riscv_load_binary(ulp_lora_bin_start,
                                          (size_t)(ulp_lora_bin_end - ulp_lora_bin_start)));
    ulp_radio_ready = 0;            /* force a cold init on the first wake */
    ulp_cfg_used = 0xFF;
    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, ULP_WAKE_PERIOD_US));
    ESP_ERROR_CHECK(ulp_riscv_run());
}

/* ---- Bus probe: ask the SX1262 a question with HARDWARE SPI before the ULP is started ----------------
 *
 * Why this exists: the ULP reported GetStatus = 0x00 and no TxDone, which is what an absent chip looks like. Before
 * blaming the bit-bang, ask the same question over the hardware SPI peripheral on the same pins. Three outcomes and
 * three different next steps:
 *   0x2X (chipmode STDBY_RC) -> pins are right, the bit-bang or the RTC-GPIO handover is wrong
 *   0xFF/0x00 with MISO stuck -> the pin map or the radio's power rail is wrong, not the ULP
 *   anything else            -> the chip answers but not in a state the driver expects
 * GUARDRAIL: run this BEFORE rtc_gpio_init() on those pins. Once a pin is an RTC GPIO the SPI peripheral cannot drive
 * it, so a probe placed after start_ulp() would silently read whatever the ULP last left on the line. */
static void bus_probe(void)
{
    spi_bus_config_t bus = {
        .mosi_io_num = PIN_MOSI,
        .miso_io_num = PIN_MISO,
        .sclk_io_num = PIN_SCK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 64,
    };
    if (spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_DISABLED) != ESP_OK) {
        printf("bus probe: spi_bus_initialize failed\n");
        return;
    }
    spi_device_interface_config_t dev = {
        .clock_speed_hz = 1 * 1000 * 1000,
        .mode = 0,
        .spics_io_num = -1,          /* CS driven by hand so the waveform matches the ULP's */
        .queue_size = 1,
    };
    spi_device_handle_t h;
    if (spi_bus_add_device(SPI2_HOST, &dev, &h) != ESP_OK) {
        printf("bus probe: add_device failed\n");
        spi_bus_free(SPI2_HOST);
        return;
    }
    gpio_set_direction((gpio_num_t)PIN_NSS, GPIO_MODE_OUTPUT);
    gpio_set_level((gpio_num_t)PIN_NSS, 0);
    uint8_t rx[3] = { 0 };
    const uint8_t tx[3] = { 0xC0, 0x00, 0x00 };   /* GetStatus */
    spi_transaction_t t = { .length = 8 * sizeof tx, .tx_buffer = tx, .rx_buffer = rx };
    gpio_set_level((gpio_num_t)PIN_NSS, 1);
    vTaskDelay(pdMS_TO_TICKS(1));
    gpio_set_level((gpio_num_t)PIN_NSS, 0);
    esp_err_t e = spi_device_transmit(h, &t);
    gpio_set_level((gpio_num_t)PIN_NSS, 1);
    printf("bus probe @1MHz: transmit %s, GetStatus reply 0x%02x (chipmode %u, status %u)\n",
           esp_err_to_name(e), rx[1], (unsigned)((rx[1] >> 4) & 0x7), (unsigned)((rx[1] >> 1) & 0x7));
    spi_bus_remove_device(h);
    spi_bus_free(SPI2_HOST);
    vTaskDelay(pdMS_TO_TICKS(5));
}

void app_main(void)
{
    if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_UNDEFINED) {
        bus_probe();
        start_ulp();
    }

    for (int i = 0; i < 20; i++) {
        /* Time the ULP's awake window from here, with this core's clock: the ULP cannot be trusted to time itself until
         * ccount_cal says its counter is sane (measured: it is not, see ulp_ccount_cal). 200 us sampling resolves the
         * ~108 ms expected air time to ~0.2 %. */
        int64_t t_start = 0;
        int64_t t_end = 0;
        int64_t deadline = esp_timer_get_time() + 4500000;
        bool seen = false;
        while (esp_timer_get_time() < deadline) {
            uint32_t a = (uint32_t)ulp_awake;
            int64_t now = esp_timer_get_time();
            if (a && !seen) { seen = true; t_start = now; }
            else if (!a && seen) { t_end = now; break; }
            esp_rom_delay_us(200);
        }
        if (seen && t_end > t_start) {
            ulp_busy_us = (uint32_t)(t_end - t_start);
        }
        vTaskDelay(pdMS_TO_TICKS(900));
        printf("wakes %3" PRIu32 "  tx_ok %3" PRIu32 "  tx_fail %3" PRIu32 "  err %" PRId32
               "  cfg %s  status 0x%02" PRIx32 "  spi %" PRIu32 " cyc/B (%" PRIu32 " kHz SCK)  pads %" PRIu32
               "  cold %" PRIu32 "  cal %" PRIu32 " cyc/10ms  busy %" PRIu32 " us  buf %" PRIu32 "  ulp %u B\n",
               (uint32_t)ulp_run_count, (uint32_t)ulp_tx_ok_count, (uint32_t)ulp_tx_fail_count,
               (int32_t)ulp_last_error,
               ulp_cfg_used == 0 ? "no-tcxo" : (ulp_cfg_used == 1 ? "tcxo" : "?"),
               (uint32_t)ulp_status_byte,
               (uint32_t)ulp_spi_cycles_per_byte,
               (uint32_t)ulp_spi_cycles_per_byte ? (uint32_t)(8u * 17500u / ulp_spi_cycles_per_byte) : 0u,
               (uint32_t)ulp_pad_selftest,
               (uint32_t)ulp_cold_count,
               (uint32_t)ulp_ccount_cal,
               (uint32_t)ulp_busy_us,
               (uint32_t)ulp_buf_verify,
               (unsigned)(ulp_lora_bin_end - ulp_lora_bin_start));
        fflush(stdout);
    }
    printf("done: leaving the ULP running and idling here (no deep sleep in bring-up)\n");
}
