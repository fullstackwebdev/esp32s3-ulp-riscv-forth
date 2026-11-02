/* sx126x_ulp_hal.h - bit-banged SPI + RTC GPIO for an SX1262, from the ULP-RISC-V.
 *
 * Target: Heltec WiFi LoRa 32 V3 (ESP32-S3 + SX1262). Pin map is the documented variant; see lora_main.c for the
 * identity check that proves it is right before any result is believed (docs/14 R16).
 */
#ifndef SX126X_ULP_HAL_H
#define SX126X_ULP_HAL_H

#include <stdint.h>
#include <stddef.h>

/* Heltec V3 SX1262 wiring (documented variant, verified by TxDone - see lora_main.c) */
#define LORA_PIN_SCK    9
#define LORA_PIN_MOSI   10
#define LORA_PIN_MISO   11
#define LORA_PIN_NSS    8
#define LORA_PIN_RESET  12
#define LORA_PIN_BUSY   13
#define LORA_PIN_DIO1   14

/* GUARDRAIL: bound BUSY waits in CYCLES, not loop iterations — an iteration count means a duration that changes with
 * the compiler's codegen (35 ms or 70 ms for the same source), so a stuck BUSY costs an unpredictable awake time. The
 * ULP has a cycle counter (ULP_RISCV_GET_CCOUNT); use it and the bound is a real time. 17.5 MHz * 0.5 s = 8.75e6. */
#define LORA_BUSY_TIMEOUT_CYCLES 8750000u

#define HAL_OK          0
#define HAL_ERR_BUSY    (-1)
#define HAL_ERR_TIMEOUT (-2)

void hal_init(void);
void hal_delay_us(uint32_t us);
void hal_delay_ms(uint32_t ms);
int  hal_wait_busy(void);
int  hal_dio1(void);
int  hal_reset(void);
int  hal_wakeup(void);
int  hal_write(const uint8_t *cmd, size_t cmd_len, const uint8_t *data, size_t data_len);
int  hal_read (const uint8_t *cmd, size_t cmd_len, uint8_t *data, size_t data_len);

/* Benchmark: clocks out `bytes` bytes and returns the measured ULP cycles per byte (0 on failure to transmit).
 * Exists so the SPI ceiling is a measurement instead of a forum figure - docs/27 carries ~235-350 kHz from a forum,
 * docs/28 derives a Forth equivalent; this is the number that settles the bus. */
uint32_t hal_bench_cycles_per_byte(uint32_t bytes);

/* Drives each output pin high, reads the RTC input register back, and returns a mask of the pins whose pad did NOT
 * follow (bit 0 SCK, 1 MOSI, 2 NSS, 3 RESET). Non-zero means the ULP is not actually driving the pads - which is what
 * a missing gpio_reset_pin(), a frozen pad, or an RTC-mux mistake looks like from the inside: every SPI transfer reads
 * MISO as 0 and every command "succeeds". */
uint32_t hal_pad_selftest(void);

#endif
