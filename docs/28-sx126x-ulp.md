# 28 — SX126x on the ULP-RISC-V, and whether it can be Forth

Branch `spi-lora`. Companion to `docs/27-spi-lora.md` (external memory, energy budget, the forum-reported ULP SPI
figures). This file holds (a) the C reference driver as supplied, reassembled, (b) a review list of what to verify in it,
and (c) the answer to the actual question: **can we implement this in Forth, on this machine?**

**Provenance.** The C below arrived as one paste with its blocks interleaved (the tail of `sx126x_ulp_hal.c` was inside
`sx126x_min.h`, the tail of `sx126x_min.c` inside `ulp_main.c`, and so on). It has been reassembled into the six files it
was clearly written as. Two of those files were **not** supplied: `sx126x_ulp_hal.h` does not appear at all, and its
contents are inferred from what the `.c` uses — §2.1 states exactly what is required and marks it inferred. Nothing here
has been compiled or run; it is reference material for a design decision, not a working driver.

---

## 1. Answer first

**Yes — and on this machine the Forth version is architecturally the *better* fit, for the reason that has nothing to do
with speed.** The SPI is ~1 % of a packet's cost; LoRa's air time dominates by two orders of magnitude. What Forth costs
us is not milliseconds, it is **bytes of ULP pool**, and that is a solvable problem because our dispatcher already loads
code from the block store into a 1 037 B window.

| | C reference | Forth on our machine |
|---|---|---|
| SPI clock | ~350 kHz (forum-reported, direct register writes) | **~30–80 kHz** (derived, §4.4) |
| 20-byte packet over SPI | ~0.5 ms | **2–6 ms** |
| cold init (~140 B of SPI) | ~4 ms | **20–40 ms** |
| same packet on air, SF9/125 kHz | **~90 ms** (§4.5) | unchanged |
| code space needed | ~1–2 KB of the 8 192 B RTC memory | a **phase** in the 1 037 B window + 3 primitives |
| fits beside the interpreter today? | **no** — 1 B of pool free | **yes, as a phase** |

---

## 2. The code, reassembled

### 2.1 `sx126x_ulp_hal.h` — **not supplied, inferred**

Required by `sx126x_ulp_hal.c`, `sx126x_min.c` and `ulp_main.c`. Names and shapes are read off the call sites; the pin
numbers are the author's, not ours, and **must not be trusted** — our board's RTC-usable pins are a hardware question.

```c
/* INFERRED - not part of the supplied paste. Every item here is required by
 * the .c files, so the real header must contain at least this. */
#ifndef SX126X_ULP_HAL_H
#define SX126X_ULP_HAL_H
#include <stdint.h>
#include <stddef.h>

#define LORA_PIN_SCK    5
#define LORA_PIN_MOSI   6
#define LORA_PIN_MISO   7
#define LORA_PIN_NSS    8
#define LORA_PIN_BUSY   9
#define LORA_PIN_DIO1   10
#define LORA_PIN_RESET  11

#define LORA_CYCLES_PER_US      17u          /* 17.5 MHz truncated - 3 % fast */
#define LORA_BUSY_TIMEOUT_ITER  200000u      /* must be < UINT32_MAX; see 3.2 */

#define HAL_OK          0
#define HAL_ERR_BUSY    (-1)

void hal_init(void);
void hal_delay_us(uint32_t us);
void hal_delay_ms(uint32_t ms);
int  hal_wait_busy(void);
int  hal_dio1(void);
int  hal_reset(void);
int  hal_wakeup(void);
int  hal_write(const uint8_t *cmd, size_t cmd_len, const uint8_t *data, size_t data_len);
int  hal_read (const uint8_t *cmd, size_t cmd_len, uint8_t *data, size_t data_len);
#endif
```

### 2.2 `sx126x_ulp_hal.c`

```c
/*
 * sx126x_ulp_hal.c - see sx126x_ulp_hal.h
 *
 * SPI mode 0 (CPOL=0, CPHA=0), MSB first, bit-banged.
 *
 * GPIO access: by default writes the RTC GPIO set/clear registers directly,
 * which was the fastest method reported on the esp32.com forum (~350 kHz SCK).
 * Define LORA_USE_ULP_GPIO_API to use the ESP-IDF ulp_riscv_gpio_* helpers
 * instead (slower, ~235 kHz reported, but easier to trust).
 *
 * The main CPU must configure the pins as RTC GPIOs BEFORE starting the ULP
 * (see host_main.c). Do NOT enable RTC GPIO hold on pins the ULP drives.
 */
#include "sx126x_ulp_hal.h"
#include "ulp_riscv.h"
#include "ulp_riscv_utils.h"

#ifdef LORA_USE_ULP_GPIO_API
#include "ulp_riscv_gpio.h"
static inline void pin_high(unsigned pin) { ulp_riscv_gpio_output_level((gpio_num_t)pin, 1); }
static inline void pin_low(unsigned pin)  { ulp_riscv_gpio_output_level((gpio_num_t)pin, 0); }
static inline unsigned pin_read(unsigned pin) { return (unsigned)ulp_riscv_gpio_get_level((gpio_num_t)pin) & 1u; }
#else
#include "soc/soc.h"
#include "soc/rtc_io_reg.h"
#ifndef BIT
#define BIT(n) (1U << (n))
#endif
static inline void pin_high(unsigned pin)
{
    REG_WRITE(RTC_GPIO_OUT_W1TS_REG, BIT(pin) << RTC_GPIO_OUT_DATA_W1TS_S);
}
static inline void pin_low(unsigned pin)
{
    REG_WRITE(RTC_GPIO_OUT_W1TC_REG, BIT(pin) << RTC_GPIO_OUT_DATA_W1TC_S);
}
static inline unsigned pin_read(unsigned pin)
{
    return ((REG_READ(RTC_GPIO_IN_REG) >> RTC_GPIO_IN_NEXT_S) >> pin) & 1u;
}
#endif

void hal_delay_us(uint32_t us)
{
    ulp_riscv_delay_cycles(us * LORA_CYCLES_PER_US);
}

void hal_delay_ms(uint32_t ms)
{
    while (ms--) {
        hal_delay_us(1000);
    }
}

void hal_init(void)
{
    pin_high(LORA_PIN_NSS);
    pin_high(LORA_PIN_RESET);
    pin_low(LORA_PIN_SCK);
}

static uint8_t spi_xfer(uint8_t out)
{
    uint8_t in = 0;
    for (int i = 0; i < 8; i++) {
        if (out & 0x80u) {
            pin_high(LORA_PIN_MOSI);
        } else {
            pin_low(LORA_PIN_MOSI);
        }
        out = (uint8_t)(out << 1);
        pin_high(LORA_PIN_SCK);
        in = (uint8_t)((in << 1) | pin_read(LORA_PIN_MISO));
        pin_low(LORA_PIN_SCK);
    }
    return in;
}

int hal_wait_busy(void)
{
    uint32_t n = LORA_BUSY_TIMEOUT_ITER;
    while (pin_read(LORA_PIN_BUSY)) {
        if (--n == 0) {
            return HAL_ERR_BUSY;
        }
    }
    return HAL_OK;
}

int hal_dio1(void)
{
    return (int)pin_read(LORA_PIN_DIO1);
}

int hal_reset(void)
{
    pin_low(LORA_PIN_RESET);
    hal_delay_us(300);              /* datasheet minimum is ~100 us */
    pin_high(LORA_PIN_RESET);
    hal_delay_ms(2);                /* let BUSY rise before we poll it */
    return hal_wait_busy();
}

int hal_wakeup(void)
{
    /* Same sequence as Semtech's reference driver: any NSS-low frame wakes it. */
    pin_low(LORA_PIN_NSS);
    (void)spi_xfer(0xC0);           /* GetStatus */
    (void)spi_xfer(0x00);
    pin_high(LORA_PIN_NSS);
    return hal_wait_busy();
}

int hal_write(const uint8_t *cmd, size_t cmd_len,
              const uint8_t *data, size_t data_len)
{
    if (hal_wait_busy() != HAL_OK) {
        return HAL_ERR_BUSY;
    }
    pin_low(LORA_PIN_NSS);
    for (size_t i = 0; i < cmd_len; i++) {
        (void)spi_xfer(cmd[i]);
    }
    for (size_t i = 0; i < data_len; i++) {
        (void)spi_xfer(data[i]);
    }
    pin_high(LORA_PIN_NSS);
    return HAL_OK;
}

int hal_read(const uint8_t *cmd, size_t cmd_len,
             uint8_t *data, size_t data_len)
{
    if (hal_wait_busy() != HAL_OK) {
        return HAL_ERR_BUSY;
    }
    pin_low(LORA_PIN_NSS);
    for (size_t i = 0; i < cmd_len; i++) {
        (void)spi_xfer(cmd[i]);
    }
    for (size_t i = 0; i < data_len; i++) {
        data[i] = spi_xfer(0x00);
    }
    pin_high(LORA_PIN_NSS);
    return HAL_OK;
}
```

### 2.3 `sx126x_min.h`

```c
/*
 * sx126x_min.h - minimal transmit-only LoRa driver for SX1262 (and SX1268 /
 * LLCC68 with minor changes) built on sx126x_ulp_hal.h.
 *
 * Opcodes and parameter layouts follow the Semtech SX1261/2 datasheet command
 * set. Verify every value against the datasheet revision for your chip/module
 * (TCXO voltage, RF switch wiring, image-calibration band, PA settings).
 */
#ifndef SX126X_MIN_H
#define SX126X_MIN_H

#include <stdint.h>

/* RF frequency register value: Hz * 2^25 / 32e6. Compile-time constant when
 * given a constant, so no 64-bit division ends up in the ULP binary. */
#define SX126X_FREQ_REG(hz) ((uint32_t)(((uint64_t)(hz) << 25) / 32000000ULL))

/* LoRa bandwidth codes for SetModulationParams */
#define SX126X_BW_125   0x04
#define SX126X_BW_250   0x05
#define SX126X_BW_500   0x06

/* Image calibration pairs (CalibrateImage), by band, per the datasheet table */
#define SX126X_IMGCAL_430_440 { 0x6B, 0x6F }
#define SX126X_IMGCAL_470_510 { 0x75, 0x81 }
#define SX126X_IMGCAL_779_787 { 0xC1, 0xC5 }
#define SX126X_IMGCAL_863_870 { 0xD7, 0xDB }
#define SX126X_IMGCAL_902_928 { 0xE1, 0xE9 }

#define SX126X_ERR_TIMEOUT   (-2)
#define SX126X_ERR_NO_TXDONE (-3)

typedef struct {
    uint32_t rf_freq_reg;     /* use SX126X_FREQ_REG(hz) */
    uint8_t  img_cal[2];      /* use SX126X_IMGCAL_* */
    uint8_t  sf;              /* 5..12 */
    uint8_t  bw;              /* SX126X_BW_* */
    uint8_t  cr;              /* 1 = 4/5 ... 4 = 4/8 */
    uint8_t  ldro;            /* low data rate optimize: 1 for SF11/12 at 125 kHz */
    int8_t   tx_dbm;          /* 14, 17, 20 or 22 on SX1262 */
    uint16_t preamble;        /* symbols, 8 is typical */
    uint8_t  use_dcdc;        /* 1 if the module has the DC-DC inductor */
    uint8_t  use_tcxo;        /* 1 if a TCXO is powered from DIO3 */
    uint8_t  tcxo_voltage;    /* 0=1.6V 1=1.7 2=1.8 3=2.2 4=2.4 5=2.7 6=3.0 7=3.3 */
    uint8_t  dio2_rf_switch;  /* 1 if DIO2 drives the TX/RX antenna switch */
} sx126x_cfg_t;

/* Full configuration after power-up. Returns 0 on success, <0 on error. */
int sx126x_cold_init(const sx126x_cfg_t *c);

/* Wake the chip, load the payload and transmit; blocks until TxDone or the
 * timeout. Assumes the radio was configured with sx126x_cold_init() and put
 * to sleep with warm start. Returns 0 on success, <0 on error/timeout. */
int sx126x_send(const sx126x_cfg_t *c, const uint8_t *buf, uint8_t len,
                uint32_t timeout_ms);

/* Put the chip to sleep. warm=1 keeps configuration (about 1 uA class). */
int sx126x_sleep(int warm);

#endif /* SX126X_MIN_H */
```

### 2.4 `sx126x_min.c`

```c
/*
 * sx126x_min.c - see sx126x_min.h
 */
#include "sx126x_min.h"
#include "sx126x_ulp_hal.h"

/* Command opcodes (SX1261/2 datasheet) */
#define OP_SET_SLEEP            0x84
#define OP_SET_STANDBY          0x80
#define OP_SET_TX               0x83
#define OP_SET_REGULATOR_MODE   0x96
#define OP_CALIBRATE            0x89
#define OP_CALIBRATE_IMAGE      0x98
#define OP_SET_PA_CONFIG        0x95
#define OP_SET_DIO_IRQ_PARAMS   0x08
#define OP_SET_DIO2_AS_RFSW     0x9D
#define OP_SET_DIO3_AS_TCXO     0x97
#define OP_SET_RF_FREQUENCY     0x86
#define OP_SET_PACKET_TYPE      0x8A
#define OP_SET_TX_PARAMS        0x8E
#define OP_SET_BUFFER_BASE      0x8F
#define OP_SET_MOD_PARAMS       0x8B
#define OP_SET_PACKET_PARAMS    0x8C
#define OP_WRITE_BUFFER         0x0E
#define OP_GET_IRQ_STATUS       0x12
#define OP_CLEAR_IRQ_STATUS     0x02
#define OP_READ_REGISTER        0x1D
#define OP_WRITE_REGISTER       0x0D

#define IRQ_TX_DONE             0x0001u
#define IRQ_TIMEOUT             0x0200u

/* Register used by the SX1262 antenna-mismatch workaround (datasheet ch. 15) */
#define REG_TX_CLAMP_CONFIG     0x08D8

static int cmd(uint8_t op, const uint8_t *p, size_t n)
{
    return hal_write(&op, 1, p, n);
}

static int cmd1(uint8_t op, uint8_t a)
{
    return cmd(op, &a, 1);
}

static int read_reg(uint16_t addr, uint8_t *val)
{
    const uint8_t c[4] = { OP_READ_REGISTER, (uint8_t)(addr >> 8), (uint8_t)addr, 0x00 };
    return hal_read(c, sizeof c, val, 1);
}

static int write_reg(uint16_t addr, uint8_t val)
{
    const uint8_t c[3] = { OP_WRITE_REGISTER, (uint8_t)(addr >> 8), (uint8_t)addr };
    return hal_write(c, sizeof c, &val, 1);
}

static int set_packet_params(const sx126x_cfg_t *c, uint8_t len)
{
    const uint8_t p[6] = {
        (uint8_t)(c->preamble >> 8), (uint8_t)c->preamble,
        0x00,   /* explicit header */
        len,
        0x01,   /* CRC on */
        0x00    /* standard IQ */
    };
    return cmd(OP_SET_PACKET_PARAMS, p, sizeof p);
}

int sx126x_cold_init(const sx126x_cfg_t *c)
{
    int e;
    uint8_t pa_duty, hp_max;
    uint8_t p[8];

    hal_init();
    if ((e = hal_reset()) != 0) return e;

    if ((e = cmd1(OP_SET_STANDBY, 0x00)) != 0) return e;          /* STDBY_RC */
    if ((e = cmd1(OP_SET_REGULATOR_MODE, c->use_dcdc ? 1 : 0)) != 0) return e;

    if (c->use_tcxo) {
        /* voltage, then 24-bit start-up delay in 15.625 us steps (5 ms = 320) */
        p[0] = c->tcxo_voltage; p[1] = 0x00; p[2] = 0x01; p[3] = 0x40;
        if ((e = cmd(OP_SET_DIO3_AS_TCXO, p, 4)) != 0) return e;
    }
    if ((e = cmd1(OP_CALIBRATE, 0x7F)) != 0) return e;             /* all blocks */

    if (c->dio2_rf_switch) {
        if ((e = cmd1(OP_SET_DIO2_AS_RFSW, 0x01)) != 0) return e;
    }

    if ((e = cmd1(OP_SET_PACKET_TYPE, 0x01)) != 0) return e;       /* LoRa */

    p[0] = (uint8_t)(c->rf_freq_reg >> 24);
    p[1] = (uint8_t)(c->rf_freq_reg >> 16);
    p[2] = (uint8_t)(c->rf_freq_reg >> 8);
    p[3] = (uint8_t)(c->rf_freq_reg);
    if ((e = cmd(OP_SET_RF_FREQUENCY, p, 4)) != 0) return e;
    if ((e = cmd(OP_CALIBRATE_IMAGE, c->img_cal, 2)) != 0) return e;

    /* PA settings for SX1262 (deviceSel = 0, paLut = 1), datasheet table */
    if (c->tx_dbm >= 22)      { pa_duty = 0x04; hp_max = 0x07; }
    else if (c->tx_dbm >= 20) { pa_duty = 0x03; hp_max = 0x05; }
    else if (c->tx_dbm >= 17) { pa_duty = 0x02; hp_max = 0x03; }
    else                      { pa_duty = 0x02; hp_max = 0x02; }
    p[0] = pa_duty; p[1] = hp_max; p[2] = 0x00; p[3] = 0x01;
    if ((e = cmd(OP_SET_PA_CONFIG, p, 4)) != 0) return e;

    /* Better resistance of the SX1262 TX to antenna mismatch */
    {
        uint8_t v;
        if ((e = read_reg(REG_TX_CLAMP_CONFIG, &v)) != 0) return e;
        if ((e = write_reg(REG_TX_CLAMP_CONFIG, (uint8_t)(v | 0x1E))) != 0) return e;
    }

    p[0] = (uint8_t)(c->tx_dbm > 22 ? 22 : c->tx_dbm);
    p[1] = 0x04;                                                    /* 200 us ramp */
    if ((e = cmd(OP_SET_TX_PARAMS, p, 2)) != 0) return e;

    p[0] = 0x00; p[1] = 0x00;                                       /* TX/RX base */
    if ((e = cmd(OP_SET_BUFFER_BASE, p, 2)) != 0) return e;

    p[0] = c->sf; p[1] = c->bw; p[2] = c->cr; p[3] = c->ldro;
    if ((e = cmd(OP_SET_MOD_PARAMS, p, 4)) != 0) return e;

    /* IRQ: TxDone and Timeout, both routed to DIO1 */
    p[0] = (uint8_t)((IRQ_TX_DONE | IRQ_TIMEOUT) >> 8);
    p[1] = (uint8_t)(IRQ_TX_DONE | IRQ_TIMEOUT);
    p[2] = p[0]; p[3] = p[1];
    p[4] = p[5] = p[6] = p[7] = 0x00;
    if ((e = cmd(OP_SET_DIO_IRQ_PARAMS, p, 8)) != 0) return e;

    return 0;
}

int sx126x_send(const sx126x_cfg_t *c, const uint8_t *buf, uint8_t len,
                uint32_t timeout_ms)
{
    int e;
    uint8_t p[3];
    uint8_t irq[3];
    uint32_t ticks, guard;

    if ((e = hal_wakeup()) != 0) return e;
    if ((e = set_packet_params(c, len)) != 0) return e;

    {
        const uint8_t wb[2] = { OP_WRITE_BUFFER, 0x00 };
        if ((e = hal_write(wb, sizeof wb, buf, len)) != 0) return e;
    }

    p[0] = 0xFF; p[1] = 0xFF;
    if ((e = cmd(OP_CLEAR_IRQ_STATUS, p, 2)) != 0) return e;

    ticks = timeout_ms * 64u;                       /* 15.625 us per tick */
    if (ticks > 0xFFFFFFu) ticks = 0xFFFFFFu;
    p[0] = (uint8_t)(ticks >> 16); p[1] = (uint8_t)(ticks >> 8); p[2] = (uint8_t)ticks;
    if ((e = cmd(OP_SET_TX, p, 3)) != 0) return e;

    /* Wait for DIO1 (TxDone or Timeout). 200 us per poll plus a margin. */
    guard = timeout_ms * 5u + 200u;
    while (!hal_dio1()) {
        if (guard-- == 0) return SX126X_ERR_TIMEOUT;
        hal_delay_us(200);
    }

    {
        const uint8_t rq[2] = { OP_GET_IRQ_STATUS, 0x00 };  /* 0x00 = status slot */
        if ((e = hal_read(rq, sizeof rq, irq, 2)) != 0) return e;
    }
    p[0] = 0xFF; p[1] = 0xFF;
    (void)cmd(OP_CLEAR_IRQ_STATUS, p, 2);

    {
        uint16_t flags = (uint16_t)(((uint16_t)irq[0] << 8) | irq[1]);
        if (!(flags & IRQ_TX_DONE)) return SX126X_ERR_NO_TXDONE;
    }
    return 0;
}

int sx126x_sleep(int warm)
{
    /* bit 2 = 1: warm start (configuration retained) */
    return cmd1(OP_SET_SLEEP, warm ? 0x04 : 0x00);
}
```

### 2.5 `ulp_main.c`

```c
/*
 * ulp_main.c - ULP-RISC-V example: send a 20-byte raw LoRa packet every
 * send_every_n timer wakes, without ever waking the main CPU.
 *
 * Build as the ULP app "ulp_main" (see CMakeLists.txt). Variables below are
 * visible to the main CPU as ulp_run_count, ulp_send_every_n, etc.
 */
#include <stdint.h>
#include "ulp_riscv.h"
#include "ulp_riscv_utils.h"
#include "sx126x_ulp_hal.h"
#include "sx126x_min.h"

/* ---- Shared with the main CPU (all 32-bit) ---- */
volatile uint32_t run_count;       /* timer wakes since the ULP was started   */
volatile uint32_t send_every_n = 1;/* set by the host; the ULP timer period
                                      has a maximum (verify on your IDF), so
                                      long intervals = count wakes            */
volatile uint32_t sensor_value;    /* host or ULP code can fill this in       */
volatile uint32_t radio_ready;     /* 0 = next send does a full cold init     */
volatile uint32_t tx_ok_count;
volatile uint32_t tx_fail_count;
volatile int32_t  last_error;      /* 0 = ok, otherwise HAL/driver error code */

/* Set to 1 to cold-init the radio on every send: costs a few ms and some
 * charge per packet, but removes any doubt about warm-start retention. */
#ifndef LORA_FORCE_COLD_INIT
#define LORA_FORCE_COLD_INIT 0
#endif

/* EU868 channel, SF9/125 kHz, +14 dBm. Edit for your region and module. */
static const sx126x_cfg_t cfg = {
    .rf_freq_reg    = SX126X_FREQ_REG(868100000UL),
    .img_cal        = SX126X_IMGCAL_863_870,
    .sf             = 9,
    .bw             = SX126X_BW_125,
    .cr             = 1,
    .ldro           = 0,
    .tx_dbm         = 14,
    .preamble       = 8,
    .use_dcdc       = 1,
    .use_tcxo       = 0,
    .tcxo_voltage   = 0,
    .dio2_rf_switch = 1,
};

static uint32_t read_sensor(void)
{
    /* Replace with RTC ADC / RTC I2C / GPIO reads. */
    return sensor_value;
}

int main(void)
{
    uint8_t pkt[20] = { 0 };
    uint32_t v, n;
    int e = 0;

    run_count++;

    n = send_every_n;
    if (n == 0) n = 1;
    if ((run_count % n) != 0) {
        ulp_riscv_halt();
        return 0;
    }

    /* 20-byte payload: marker, run counter, sensor value */
    pkt[0] = 0xA5;
    v = run_count;
    pkt[1] = (uint8_t)(v >> 24); pkt[2] = (uint8_t)(v >> 16);
    pkt[3] = (uint8_t)(v >> 8);  pkt[4] = (uint8_t)v;
    v = read_sensor();
    pkt[5] = (uint8_t)(v >> 24); pkt[6] = (uint8_t)(v >> 16);
    pkt[7] = (uint8_t)(v >> 8);  pkt[8] = (uint8_t)v;

    hal_init();

    if (LORA_FORCE_COLD_INIT || !radio_ready) {
        e = sx126x_cold_init(&cfg);
        if (e == 0) {
            radio_ready = 1;
        }
    }
    if (e == 0) {
        e = sx126x_send(&cfg, pkt, sizeof pkt, 5000);
    }

    /* Always try to put the chip back to sleep, even after an error. */
    (void)sx126x_sleep(1);

    if (e == 0) {
        tx_ok_count++;
    } else {
        tx_fail_count++;
        radio_ready = 0;       /* force a clean re-init next time */
    }
    last_error = e;

    ulp_riscv_halt();
    return 0;
}
```

### 2.6 `host_main.c`

```c
/*
 * host_main.c - main-CPU side (ESP-IDF, ESP32-S3). Save as main/main.c.
 *
 * Boot once: configure the pins as RTC GPIOs, load/start the ULP-RISC-V,
 * then deep-sleep. The ULP keeps running on its timer and sends LoRa packets.
 *
 * Function names are from ESP-IDF 5.x as I remember them. Check them against
 * your IDF version, especially the ULP timer-period call.
 */
#include <stdio.h>
#include "esp_sleep.h"
#include "esp_err.h"
#include "driver/gpio.h"
#include "driver/rtc_io.h"
#include "ulp_riscv.h"
#include "ulp_main.h"            /* generated: exposes ulp_* shared variables */

/* Keep these in sync with the LORA_PIN_* values in sx126x_ulp_hal.h */
#define PIN_SCK    GPIO_NUM_5
#define PIN_MOSI   GPIO_NUM_6
#define PIN_MISO   GPIO_NUM_7
#define PIN_NSS    GPIO_NUM_8
#define PIN_BUSY   GPIO_NUM_9
#define PIN_DIO1   GPIO_NUM_10
#define PIN_RESET  GPIO_NUM_11

#define ULP_WAKE_PERIOD_US   (60ULL * 1000000ULL)   /* keep within the timer's max */
#define SEND_EVERY_N_WAKES   10                      /* 60 s * 10 = every 10 min   */

extern const uint8_t ulp_main_bin_start[] asm("_binary_ulp_main_bin_start");
extern const uint8_t ulp_main_bin_end[]   asm("_binary_ulp_main_bin_end");

static void rtc_out(gpio_num_t pin, int level)
{
    ESP_ERROR_CHECK(rtc_gpio_init(pin));
    ESP_ERROR_CHECK(rtc_gpio_set_direction(pin, RTC_GPIO_MODE_OUTPUT_ONLY));
    ESP_ERROR_CHECK(rtc_gpio_set_level(pin, level));
    ESP_ERROR_CHECK(rtc_gpio_pullup_dis(pin));
    ESP_ERROR_CHECK(rtc_gpio_pulldown_dis(pin));
    /* Do NOT call rtc_gpio_hold_en() here: it would freeze the pad and the
     * ULP could no longer drive it. */
}

static void rtc_in(gpio_num_t pin)
{
    ESP_ERROR_CHECK(rtc_gpio_init(pin));
    ESP_ERROR_CHECK(rtc_gpio_set_direction(pin, RTC_GPIO_MODE_INPUT_ONLY));
    ESP_ERROR_CHECK(rtc_gpio_pullup_dis(pin));
    ESP_ERROR_CHECK(rtc_gpio_pulldown_dis(pin));
}

static void start_ulp(void)
{
    rtc_out(PIN_SCK,   0);
    rtc_out(PIN_MOSI,  0);
    rtc_out(PIN_NSS,   1);   /* idle high; also fit an external pull-up */
    rtc_out(PIN_RESET, 1);   /* idle high; also fit an external pull-up */
    rtc_in(PIN_MISO);
    rtc_in(PIN_BUSY);
    rtc_in(PIN_DIO1);

    ESP_ERROR_CHECK(ulp_riscv_load_binary(ulp_main_bin_start,
                                          ulp_main_bin_end - ulp_main_bin_start));

    /* Initial values for the shared variables (the ULP starts after this). */
    ulp_send_every_n = SEND_EVERY_N_WAKES;
    ulp_sensor_value = 0;
    ulp_radio_ready  = 0;

    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, ULP_WAKE_PERIOD_US));
    ESP_ERROR_CHECK(ulp_riscv_run());
}

void app_main(void)
{
    esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();

    if (cause == ESP_SLEEP_WAKEUP_UNDEFINED) {
        /* Power-on or reset: (re)load and start the ULP. Do NOT reload on
         * other wake causes, or the ULP's state would be wiped. */
        start_ulp();
    } else {
        printf("Woke up, cause %d. ULP sent %lu ok, %lu failed, last error %ld\n",
               (int)cause,
               (unsigned long)ulp_tx_ok_count,
               (unsigned long)ulp_tx_fail_count,
               (long)(int32_t)ulp_last_error);
    }

    /* Keep RTC slow memory and the ULP powered in deep sleep. The ULP never
     * wakes the main CPU in this example; add a timer wake-up if you want a
     * periodic report, e.g. esp_sleep_enable_timer_wakeup(3600ULL*1000000). */
    ESP_ERROR_CHECK(esp_sleep_enable_ulp_wakeup());
    esp_deep_sleep_start();
}
```

---

## 3. What to check in the C before copying any of it

Not claimed bugs — items that will bite in a specific situation, in the spirit of `docs/14-probe-rules.md`.

1. **`sx126x_ulp_hal.h` was never supplied.** The inferred version in §2.1 is a guess at the pin map. Our board's
   RTC-capable pins are a hardware fact we have not established (§6 says this about the LoRa board specifically).
2. **`LORA_BUSY_TIMEOUT_ITER` is a loop count, not a time.** `200000` iterations at ~6 cycles each is ~70 ms at 17.5 MHz
   — but if the poll loop compiles to 3 cycles it is 35 ms. It must be derived from a measured loop, not guessed, or a BUSY
   that never clears costs an unpredictable time in the one place the ULP should be sleeping.
3. **`LORA_CYCLES_PER_US` = 17 truncates 17.5 MHz** → every delay is ~3 % short. Harmless at millisecond scale, but
   `hal_delay_us(200)` in the DIO1 poll is the loop's tick, so the actual poll period is 194 µs. Fine — just do not
   reason in whole milliseconds afterwards.
4. **MISO is sampled immediately after SCK rises**, with no settling gap. SPI mode 0 is sampled on the rising edge, so
   this is correct *in principle* — but at 350 kHz the slave has 2.8 µs of half-period; the ULP's own store-then-load pair
   supplies most of it by accident. If it misreads, the fix is a `nop` after `pin_high(SCK)`, not a slower clock.
5. **DIO1 is level-sensitive and latched.** `sx126x_send` clears the IRQ *before* `SET_TX`, which is what makes the
   `while (!hal_dio1())` wait correct. Remove that clear and the wait exits instantly on the previous packet's flag, and the
   `TX_DONE` check then reports `NO_TXDONE` — a failure that looks like a radio fault and is a missing clear.
6. **After an error, the pin/flag state is whatever the failure left.** `ulp_main.c` handles this correctly (sleeps the
   radio, sets `radio_ready = 0`); any Forth port must keep that discipline, because our own F-140 was exactly this class
   of bug (a status handed back where an address belongs).
7. **`esp_sleep_enable_ulp_wakeup()` with no `ulp_riscv_wakeup_main_processor()` call** is inert: the main CPU never
   wakes, so the `printf` in the `else` branch is unreachable without a separate timer wake-up. Harmless, but it reads as
   if it does something.
8. **`SX126X_FREQ_REG` relies on the constant folding** the comment promises. If `hz` is ever a variable, a 64-bit divide
   lands in the ULP binary — kilobytes nobody budgeted for.

---

## 4. Can it be Forth? Yes — and this is where the arithmetic lands

### 4.1 What "in Forth" means on our machine

Our interpreter already **is** the ULP program: the engine (`src/uforth.c`) and its I/O bridge (`src/ulp_repl.c`) are what
run on the ULP-RISC-V at 17.5 MHz, with the main core servicing block reads over the handshake (F-132). Consequences that
shape this decision:

* a Forth word costs **bytes in the 7 892 B pool**, which is currently **7 891 / 7 892 — 1 B free**;
* app code does not sit resident: it is a **phase** — compiled definitions living in a **1 037 B window**, adopted from a
  descriptor in the block store by the dispatcher (`56 GO`, docs/26). That is exactly the mechanism a LoRa driver wants;
* a new *primitive* is a `.c` edit to the token table, so it lands in **both** the host and ULP builds and grows the pool
  by its compiled size (calibration: adding a counter and its increment cost **12 B**).

### 4.2 Which parts must be primitives, and which can be Forth

| piece | must be C | why |
|---|---|---|
| pin write / pin read | **yes** | needs the RTC GPIO registers; a Forth `!` to an absolute address works but costs tokens per toggle |
| microsecond delay | **yes** | needs `ulp_riscv_delay_cycles` |
| byte out / byte in (the bit loop) | **strongly preferred** | 8 iterations of shift-mask-toggle-read: the one place tokens hurt |
| command encode + send | no | Forth is *better* here: readable opcode tables, patchable over the block store |
| init sequence, PA table, img-cal pairs | no | data, and data belongs in the block store, not in code |
| TX/wait/IRQ/clear/retry policy | no | the interesting part, and where a phase's 1 037 B buys the most |

So the shape is **three or four primitives + a phase**, not a C driver.

### 4.3 The byte budget, which is the real constraint

| item | bytes |
|---|---|
| ULP pool today | **7 891 / 7 892** (1 B free) |
| `PIN! ( v pin -- )` + `PIN@ ( pin -- v )` + `DUS ( us -- )` | ~60–110 B estimated, **needs permission and a build to know** |
| `SPIX ( b -- b' )` bit-loop primitive | ~60–120 B estimated |
| the driver as a phase (opcode table, cfg block, init, TX, sleep, retry) | ~450–900 B of the 1 037 B window |

**Conclusion: the Forth driver cannot coexist with the current interpreter in the same image** — not because it is too
slow, but because the pool is full. It fits as a **phase**, which is the architecture we already built.

### 4.4 How slow would the bit loop be in pure Forth? (derived, not measured)

Per bit, a Forth loop body is realistically 6–10 threaded tokens: mask, test, branch, pin write, clock high, read MISO,
clock low, shift. At ~2–4 µs per token on the ULP (derived from 17.5 MHz with a multi-cycle dispatch per token — **this is
the number to measure, and it cannot be measured without a board**):

```
6 tokens/bit × 3 µs  = 18 µs/bit   -> 144 µs/byte  -> ~7 KB/s  -> SCK ~56 kHz
10 tokens/bit × 3 µs = 30 µs/bit   -> 240 µs/byte  -> ~4 KB/s  -> SCK ~33 kHz
```

Call it **30–80 kHz**, versus the C reference's ~350 kHz: **4–10× slower**, exactly as one would expect from an
interpreter.

### 4.5 Why 4–10× slower does not matter here

A 20-byte packet at SF9 / 125 kHz: symbol time = 2⁹ / 125 000 = **4.096 ms**; preamble 8 symbols ≈ 33 ms; payload
(20 B, CR 4/5, explicit header, CRC on) = 8 + ⌈(160 − 36 + 28 + 16)/28⌉ = 14 symbols ≈ 57 ms → **~90 ms on air**.

| operation | C | Forth | share of one packet |
|---|---|---|---|
| warm-start TX path (set packet params + write 20 B buffer + set TX + get IRQ ≈ 35 B of SPI) | ~1 ms | **4–9 ms** | 5–10 % |
| cold init (~140 B of SPI + 5 ms TCXO/calibration) | ~9 ms | **25–40 ms** | ~30 %, **once** |
| on air | 90 ms | 90 ms | — |

So: **warm start, and the SPI cost is noise.** Cold-initialising every packet is what would make it visible — which is
exactly what `LORA_FORCE_COLD_INIT` in the C is for debugging, and what our phase should keep as a debug flag, not the
default.

### 4.6 What a Forth version would look like

A phase, `examples/apps/lora/lora1.fs`, roughly 40 lines:

* one descriptor's worth of **data** in the block store: the cfg (freq reg, sf/bw/cr, PA nibbles, img-cal pair) as fixed
  offsets — **multiples of 4**, because F-136: an unaligned 32-bit load is legal on the host and traps on rv32;
* `: CMD ( op a n -- ) ... ;` wrapping `SPIX`, with `BUSY` polled before and after — the level, not an edge (F-132);
* `: INIT ... ;` the ten-command sequence, with each opcode written as a named constant in the phase, so it is patchable;
* `: SEND ( len -- ok ) ... CLEAR TICK TX WAIT IRQ? ;` with the DIO1 wait bounded by a **counted** loop, never a
  guessed busy-wait, and the clear-before-TX ordering that makes the wait correct (§3.5);
* `: SLEEP ( -- ) 84 04 ;` and the retry policy in Forth, where changing it costs zero pool bytes.

Everything unpleasant (registers, cycles, bit ordering) collapses into three primitives; everything we would want to
iterate on stays in Forth and in the store.

---

## 5. Verdict: three architectures, in order of fit

**A. LoRa as a Forth phase (recommended).** 3–4 SPI/GPIO primitives in the token table (`.c`, permission required, ~120–230
B of pool — which does *not* fit in the 1 B free, so something must move first), the driver itself a phase in the 1 037 B
window, records into the block store, radio asleep between wakes. Keeps our whole toolchain: linter, splitter, screen
harness, `#u` telemetry, hop discipline.

**B. The C driver compiled into the ULP image.** Fast and proven-shaped, but it and the interpreter cannot both fit
(§4.3); this is a *different firmware*, not an addition. Choose it only if the LoRa node does not need Forth at all — in
which case the interesting question disappears.

**C. Radio on the main core, ULP as the alarm clock.** ULP counts timer wakes and nothing else; the main CPU wakes, drives
hardware SPI + DMA (megabits/s), transmits, sleeps again. Cheapest in bytes, best throughput, worst energy: the main CPU's
awake cost dwarfs the ULP's. Right answer for *bulk* data, wrong answer for *months on a coin cell*.

The energy question from `docs/27` decides between A and C: if the record rate is a few bytes a minute, A; if it is
kilobytes an hour, C.

## 6. What to measure first (needs a board, so this is the next session's work)

1. **Token cost on the ULP** — the one number §4.4 rests on. A counted loop of known tokens, timed by the main core via
   the handshake we already trust. Without it every figure above is an estimate.
2. **The bit-loop**: same loop as `SPIX`, measured as bytes/second.
3. **The size build**: `riscv32-esp-elf-size` on the phase and on the primitives, against the 7 892 B budget that
   `flash_safe.sh` already enforces.
4. **Warm-start retention**: does `SET_SLEEP(0x04)` really keep the configuration across the ULP's own sleep windows? The C
   has a debug flag for it precisely because this is not certain.
5. **The LoRa board's pin map** — which pins are RTC-capable and free — a hardware fact, established before any of the
   above.
