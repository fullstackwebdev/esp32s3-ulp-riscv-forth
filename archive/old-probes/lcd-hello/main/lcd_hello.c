/* lcd_hello.c — bring-up test for a 1602A (HD44780) on an ESP32-S3, 4-bit mode.
 *
 * Purpose: prove the WIRING before any ULP work. If this prints, the panel is
 * wired correctly and the same 7-pin protocol can move to the coprocessor.
 *
 * Wiring assumed (see docs/09-display-wiring.md):
 *   LCD 1 VSS -> GND        LCD 2 VDD -> 5V        LCD 3 V0 -> pot wiper or 1k to GND
 *   LCD 4 RS  -> GPIO1      LCD 5 RW  -> GND (!)   LCD 6 E  -> GPIO2
 *   LCD 11..14 D4..D7 -> GPIO4,5,6,7              LCD 7..10 D0..D3 -> unconnected
 *   LCD 15 A -> 220R -> 5V  LCD 16 K -> GND
 *
 * GUARDRAIL: RW must stay grounded — it is deliberately NOT a GPIO here. On a 5 V panel,
 * RW high makes the HD44780 drive D4-D7 as 5 V outputs into 3.3 V ESP32 pins and kills them.
 * That is also why this driver never reads the busy flag and uses fixed delays instead.
 *
 * GUARDRAIL: line 2 of a 1602A starts at DDRAM 0x40, not 0x10. A naive row*16+col
 * address prints the second line in the middle of the first — the classic 1602 bug.
 *
 * GUARDRAIL: never GPIO19/20 (native USB D+/-), 26-37 (flash/PSRAM), 43/44 (UART0),
 * 0/3/45/46 (strapping). Driving 19/20 has already wedged this board once in this project.
 */
#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_rom_sys.h"

#define LCD_RS  GPIO_NUM_1
#define LCD_E   GPIO_NUM_2
#define LCD_D4  GPIO_NUM_4
#define LCD_D5  GPIO_NUM_5
#define LCD_D6  GPIO_NUM_6
#define LCD_D7  GPIO_NUM_7

static const char *TAG = "lcd";

static inline void us(int n) { esp_rom_delay_us(n); }
static inline void ms(int n) { vTaskDelay(pdMS_TO_TICKS(n) + 1); }

static void strobe(void)
{
    gpio_set_level(LCD_E, 1);
    us(1);
    gpio_set_level(LCD_E, 0);
    us(50);
}

/* send one nibble, high four bits of v */
static void nibble(uint8_t v)
{
    gpio_set_level(LCD_D4, (v >> 0) & 1);
    gpio_set_level(LCD_D5, (v >> 1) & 1);
    gpio_set_level(LCD_D6, (v >> 2) & 1);
    gpio_set_level(LCD_D7, (v >> 3) & 1);
    strobe();
}

static void cmd(uint8_t c)
{
    gpio_set_level(LCD_RS, 0);
    nibble(c >> 4);
    nibble(c & 0x0F);
    if (c == 0x01 || c == 0x02) ms(2); else us(50);
}

static void putc_lcd(char c)
{
    gpio_set_level(LCD_RS, 1);
    nibble((uint8_t)c >> 4);
    nibble((uint8_t)c & 0x0F);
    us(50);
}

static void puts_lcd(const char *s) { while (*s) putc_lcd(*s++); }

/* row 0..1, col 0..15 */
static void at(int row, int col) { cmd((uint8_t)(0x80 | ((row ? 0x40 : 0x00) | (col & 0x3F)))); }

static void lcd_init(void)
{
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << LCD_RS) | (1ULL << LCD_E) | (1ULL << LCD_D4) |
                        (1ULL << LCD_D5) | (1ULL << LCD_D6) | (1ULL << LCD_D7),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&io));

    ms(50);                 /* let VDD settle */
    gpio_set_level(LCD_RS, 0);

    /* force 8-bit state three times, then switch to 4-bit — the datasheet wake-up dance */
    nibble(0x3); ms(5);
    nibble(0x3); ms(1);
    nibble(0x3); ms(1);
    nibble(0x2); ms(1);     /* now in 4-bit */

    cmd(0x28);              /* function set: 4-bit, 2 lines, 5x8 */
    cmd(0x08);              /* display off */
    cmd(0x01);              /* clear */
    cmd(0x06);              /* entry mode: increment, no shift */
    cmd(0x0C);              /* display on, cursor off, blink off */
}

void app_main(void)
{
    ESP_LOGI(TAG, "1602A bring-up: RS=1 E=2 D4=4 D5=5 D6=6 D7=7, RW tied to GND");
    lcd_init();

    /* GUARDRAIL: for bring-up, write once and leave it. A periodic rewrite makes a flickering
     * panel look like a wiring fault, and a static image proves the write landed and held
     * rather than being re-sent every second. */
    at(0, 0); puts_lcd("hello world");
    at(1, 0); puts_lcd("1602a ok");
    ESP_LOGI(TAG, "wrote: hello world / 1602a ok — static, no refresh");

    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
