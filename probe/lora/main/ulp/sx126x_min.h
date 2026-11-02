/* sx126x_min.h - transmit-only SX1262 driver on sx126x_ulp_hal.h (docs/28 §2.3, adapted for ESP-IDF 5.4 ULP-RISC-V) */
#ifndef SX126X_MIN_H
#define SX126X_MIN_H

#include <stdint.h>

/* RF frequency register value: Hz * 2^25 / 32e6, compile-time when given a constant.
 * GUARDRAIL: keep the argument a literal. If it is ever a variable, a 64-bit divide is dragged into the ULP image,
 * which is kilobytes nobody budgeted for (docs/28 §3.8). */
#define SX126X_FREQ_REG(hz) ((uint32_t)(((uint64_t)(hz) << 25) / 32000000ULL))

#define SX126X_BW_125   0x04
#define SX126X_BW_250   0x05
#define SX126X_BW_500   0x06

#define SX126X_IMGCAL_863_870 { 0xD7, 0xDB }
#define SX126X_IMGCAL_902_928 { 0xE1, 0xE9 }

#define SX126X_ERR_TIMEOUT   (-3)
#define SX126X_ERR_NO_TXDONE (-4)

typedef struct {
    uint32_t rf_freq_reg;
    uint8_t  img_cal[2];
    uint8_t  sf;
    uint8_t  bw;
    uint8_t  cr;
    uint8_t  ldro;
    int8_t   tx_dbm;
    uint16_t preamble;
    uint8_t  use_dcdc;
    uint8_t  use_tcxo;
    uint8_t  tcxo_voltage;
    uint8_t  dio2_rf_switch;
} sx126x_cfg_t;

int sx126x_cold_init(const sx126x_cfg_t *c);
int sx126x_send(const sx126x_cfg_t *c, const uint8_t *buf, uint8_t len, uint32_t timeout_ms);
int sx126x_sleep(int warm);

/* Reads the chip's own status byte (GetStatus, opcode 0xC0): chip mode in bits 6:4, command status in bits 3:1.
 * This is the identity check for the pin map - a wrong wiring cannot produce a plausible status. */
int sx126x_status(uint8_t *out);

#endif
