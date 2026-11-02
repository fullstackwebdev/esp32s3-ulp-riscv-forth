/* sx126x_ulp_hal.c - see sx126x_ulp_hal.h
 *
 * SPI mode 0 (CPOL=0, CPHA=0), MSB first, bit-banged from the ULP-RISC-V.
 */
// GUARDRAIL: this file is a COPY of probe/lora/main/ulp/sx126x_ulp_hal.c, byte-identical except the header name,
// because F-175 hand-transcribed hal_init into our own source and a hand transcription cannot prove equivalence -
// only the same compiled instructions can. Keep it verbatim; if the reference changes, re-copy it, do not retype it.
#include "hal_engine.h"

#include "soc/rtc_io_reg.h"
#include "soc/soc.h"
#include "ulp_riscv_gpio.h"
#include "ulp_riscv_utils.h"

/* GUARDRAIL: write the RTC GPIO set/clear registers directly instead of calling ulp_riscv_gpio_output_level(). The
 * helper uses REG_SET_FIELD, i.e. a read-modify-write; the direct write is one store. That RMW is exactly what the
 * forum reports as the difference between ~235 kHz and ~350 kHz SPI on this core (docs/27), so it is not a
 * micro-optimisation, it is most of the bus. */
/* GUARDRAIL: the RTC GPIO output data field starts at bit 10, not bit 0 (RTC_GPIO_OUT_DATA_W1TS_S == 10 on the S3).
 * Writing BIT(pin) unshifted lands ten bits below the field, so every write is silently discarded: the ULP runs, the
 * SPI loop executes, MISO reads 0, GetStatus returns 0x00, and every command "succeeds" while the pads never move. This
 * cost a bring-up cycle and was only caught by a pad read-back inside the ULP (hal_pad_selftest) - the hardware-SPI
 * probe on the same pins read a healthy 0x2a the whole time, which is what ruled the wiring out. Always build the value
 * with the register's own *_S macro; never hand-roll a shift for a field you did not look up. */
static inline void pin_high(uint32_t pin)
{
    REG_WRITE(RTC_GPIO_OUT_W1TS_REG, BIT(pin) << RTC_GPIO_OUT_DATA_W1TS_S);
}

static inline void pin_low(uint32_t pin)
{
    REG_WRITE(RTC_GPIO_OUT_W1TC_REG, BIT(pin) << RTC_GPIO_OUT_DATA_W1TC_S);
}

static inline uint32_t pin_read(uint32_t pin)
{
    return (REG_READ(RTC_GPIO_IN_REG) >> RTC_GPIO_IN_NEXT_S >> pin) & 1u;
}

void hal_delay_us(uint32_t us)
{
    /* ULP_RISCV_CYCLES_PER_US is 17.5 at the 17.5 MHz ULP clock; us*17+us/2 is that in integers without a 64-bit
     * divide, which the ULP would have to synthesise. */
    ulp_riscv_delay_cycles(us * 17u + us / 2u);
}

void hal_delay_ms(uint32_t ms)
{
    while (ms--) {
        hal_delay_us(1000);
    }
}

/* Called by the ULP at the start of every wake: the pads are already RTC GPIOs (the main core did that before
 * starting the ULP), so only directions and idle levels are set here. */
void hal_init(void)
{
    ulp_riscv_gpio_init(LORA_PIN_SCK);
    ulp_riscv_gpio_init(LORA_PIN_MOSI);
    ulp_riscv_gpio_init(LORA_PIN_NSS);
    ulp_riscv_gpio_init(LORA_PIN_RESET);
    ulp_riscv_gpio_init(LORA_PIN_MISO);
    ulp_riscv_gpio_init(LORA_PIN_BUSY);
    ulp_riscv_gpio_init(LORA_PIN_DIO1);

    ulp_riscv_gpio_output_enable(LORA_PIN_SCK);
    ulp_riscv_gpio_output_enable(LORA_PIN_MOSI);
    ulp_riscv_gpio_output_enable(LORA_PIN_NSS);
    ulp_riscv_gpio_output_enable(LORA_PIN_RESET);

    ulp_riscv_gpio_input_enable(LORA_PIN_MISO);
    ulp_riscv_gpio_input_enable(LORA_PIN_BUSY);
    ulp_riscv_gpio_input_enable(LORA_PIN_DIO1);

#if !defined(HAL_NOPULL)
    /* GUARDRAIL: F-173 - the one-question version of the previous cut. Everything in hal_init is kept EXCEPT these two
     * pull operations, so a LOST answer can only mean the pull writes are what opens the pad path (the earlier cut could
     * not say that, because it also deleted output_enable and so proved nothing). */
    ulp_riscv_gpio_pullup_disable(LORA_PIN_MISO);
    ulp_riscv_gpio_pulldown_disable(LORA_PIN_MISO);
#endif

#if !defined(HAL_NOLEVEL)
    /* GUARDRAIL: F-174 - the complement of F-173. Pulls proved unnecessary, so the remaining candidates inside hal_init
     * are these three level writes. Deleting only them keeps every pad configuration call intact: if the store LOSTS, the
     * gate is "the ULP must drive the pad levels itself, after configuring the pads" - which the Forth driver does not do
     * today (its levels come from the HP core at boot), and that is an actionable fix rather than a mystery. */
    pin_high(LORA_PIN_NSS);
    pin_high(LORA_PIN_RESET);
    pin_low(LORA_PIN_SCK);
#endif   /* HAL_NOLEVEL */
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
        /* GUARDRAIL: sample MISO right after SCK rises (SPI mode 0 samples on the rising edge). The ULP's own
         * store->load pair before the input read supplies the settling time; do not "fix" a bad read by lowering the
         * clock until the slave's 2.8 us half-period has been checked first. */
        in = (uint8_t)((in << 1) | pin_read(LORA_PIN_MISO));
        pin_low(LORA_PIN_SCK);
    }
    return in;
}

int hal_wait_busy(void)
{
    /* GUARDRAIL: bound by cycles. See the header comment: an iteration count is a duration that moves when the codegen
     * moves. This is also the exact mistake docs/28 §3.2 flags in the reference driver. */
    uint32_t start = ULP_RISCV_GET_CCOUNT();
    while (pin_read(LORA_PIN_BUSY)) {
        if ((uint32_t)(ULP_RISCV_GET_CCOUNT() - start) > LORA_BUSY_TIMEOUT_CYCLES) {
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
    hal_delay_us(300);
    pin_high(LORA_PIN_RESET);
    hal_delay_ms(2);
    return hal_wait_busy();
}

int hal_wakeup(void)
{
    pin_low(LORA_PIN_NSS);
    (void)spi_xfer(0xC0);   /* GetStatus: any NSS-low frame wakes the chip from sleep */
    (void)spi_xfer(0x00);
    pin_high(LORA_PIN_NSS);
    return hal_wait_busy();
}

int hal_write(const uint8_t *cmd, size_t cmd_len, const uint8_t *data, size_t data_len)
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

int hal_read(const uint8_t *cmd, size_t cmd_len, uint8_t *data, size_t data_len)
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

uint32_t hal_pad_selftest(void)
{
    uint32_t mask = 0;
    const uint32_t outs[4] = { LORA_PIN_SCK, LORA_PIN_MOSI, LORA_PIN_NSS, LORA_PIN_RESET };
    for (uint32_t i = 0; i < 4; i++) {
        uint32_t pin = outs[i];
        /* GUARDRAIL: RTC_GPIO_IN only reports a pad whose input buffer (RTC_IO_x_FUN_IE) is enabled. Reading back an
         * OUTPUT pin without enabling the input first returns 0 for every pin - which reads exactly like "the writes do
         * not land" and sent this bring-up after the wrong fault (the writes were fine; the readback was blind). */
        ulp_riscv_gpio_input_enable(pin);
        pin_high(pin);
        /* a couple of cycles for the pad to follow; the RTC GPIO output is asynchronous but the read is not instant */
        ulp_riscv_delay_cycles(60);
        if (pin_read(pin) == 0) {
            mask |= (1u << i);
        }
        pin_low(pin);
        ulp_riscv_delay_cycles(60);
        if (pin_read(pin) != 0) {
            mask |= (1u << i);
        }
        ulp_riscv_gpio_input_disable(pin);   /* leave the outputs as outputs: an enabled input buffer costs current */
    }
    pin_high(LORA_PIN_NSS);
    pin_high(LORA_PIN_RESET);
    return mask;
}

uint32_t hal_bench_cycles_per_byte(uint32_t bytes)
{
    if (bytes == 0) {
        return 0;
    }
    /* One transaction, so the fixed NSS/BUSY overhead is excluded and what is left is the bit loop itself. */
    uint32_t start = ULP_RISCV_GET_CCOUNT();
    pin_low(LORA_PIN_NSS);
    for (uint32_t i = 0; i < bytes; i++) {
        (void)spi_xfer((uint8_t)i);
    }
    pin_high(LORA_PIN_NSS);
    uint32_t cycles = (uint32_t)(ULP_RISCV_GET_CCOUNT() - start);
    return cycles / bytes;
}
