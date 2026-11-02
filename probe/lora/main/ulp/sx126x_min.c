/* sx126x_min.c - see sx126x_min.h */
#include "sx126x_min.h"
#include "sx126x_ulp_hal.h"
#include "ulp_riscv_utils.h"

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
#define OP_GET_STATUS           0xC0
#define OP_READ_BUFFER          0x1E

#define IRQ_TX_DONE             0x0001u
#define IRQ_TIMEOUT             0x0200u

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

int sx126x_status(uint8_t *out)
{
    const uint8_t c[2] = { OP_GET_STATUS, 0x00 };
    return hal_read(c, sizeof c, out, 1);
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

    if ((e = cmd1(OP_SET_STANDBY, 0x00)) != 0) return e;            /* STDBY_RC */
    if ((e = cmd1(OP_SET_REGULATOR_MODE, c->use_dcdc ? 1 : 0)) != 0) return e;

    if (c->use_tcxo) {
        /* voltage, then a 24-bit start-up delay in 15.625 us steps; 5 ms = 320 = 0x000140 */
        p[0] = c->tcxo_voltage; p[1] = 0x00; p[2] = 0x01; p[3] = 0x40;
        if ((e = cmd(OP_SET_DIO3_AS_TCXO, p, 4)) != 0) return e;
    }
    if ((e = cmd1(OP_CALIBRATE, 0x7F)) != 0) return e;              /* calibrate all blocks */

    if (c->dio2_rf_switch) {
        if ((e = cmd1(OP_SET_DIO2_AS_RFSW, 0x01)) != 0) return e;
    }

    if ((e = cmd1(OP_SET_PACKET_TYPE, 0x01)) != 0) return e;        /* LoRa */

    p[0] = (uint8_t)(c->rf_freq_reg >> 24);
    p[1] = (uint8_t)(c->rf_freq_reg >> 16);
    p[2] = (uint8_t)(c->rf_freq_reg >> 8);
    p[3] = (uint8_t)(c->rf_freq_reg);
    if ((e = cmd(OP_SET_RF_FREQUENCY, p, 4)) != 0) return e;
    if ((e = cmd(OP_CALIBRATE_IMAGE, c->img_cal, 2)) != 0) return e;

    /* PA settings for SX1262 (deviceSel = 0, paLut = 1) */
    if (c->tx_dbm >= 22)      { pa_duty = 0x04; hp_max = 0x07; }
    else if (c->tx_dbm >= 20) { pa_duty = 0x03; hp_max = 0x05; }
    else if (c->tx_dbm >= 17) { pa_duty = 0x02; hp_max = 0x03; }
    else                      { pa_duty = 0x02; hp_max = 0x02; }
    p[0] = pa_duty; p[1] = hp_max; p[2] = 0x00; p[3] = 0x01;
    if ((e = cmd(OP_SET_PA_CONFIG, p, 4)) != 0) return e;

    {   /* SX1262 antenna-mismatch workaround (datasheet ch. 15) */
        uint8_t v;
        if ((e = read_reg(REG_TX_CLAMP_CONFIG, &v)) != 0) return e;
        if ((e = write_reg(REG_TX_CLAMP_CONFIG, (uint8_t)(v | 0x1E))) != 0) return e;
    }

    p[0] = (uint8_t)(c->tx_dbm > 22 ? 22 : c->tx_dbm);
    p[1] = 0x04;                                                    /* 200 us ramp */
    if ((e = cmd(OP_SET_TX_PARAMS, p, 2)) != 0) return e;

    p[0] = 0x00; p[1] = 0x00;                                       /* TX/RX buffer base */
    if ((e = cmd(OP_SET_BUFFER_BASE, p, 2)) != 0) return e;

    p[0] = c->sf; p[1] = c->bw; p[2] = c->cr; p[3] = c->ldro;
    if ((e = cmd(OP_SET_MOD_PARAMS, p, 4)) != 0) return e;

    /* TxDone + Timeout, both routed to DIO1 */
    p[0] = 0xFF;
    p[1] = 0xFF;
    p[2] = p[0]; p[3] = p[1];
    p[4] = p[5] = p[6] = p[7] = 0x00;
    if ((e = cmd(OP_SET_DIO_IRQ_PARAMS, p, 8)) != 0) return e;

    return 0;
}

int sx126x_verify_buffer(const uint8_t *buf, uint8_t len)
{
    uint8_t got[32];
    uint8_t cmd[3] = { OP_READ_BUFFER, 0x00, 0x00 };   /* opcode, offset, then read (dummy clock) */
    if (len > sizeof got) {
        return -1;
    }
    if (hal_read(cmd, sizeof cmd, got, len) != HAL_OK) {
        return -2;
    }
    for (uint8_t i = 0; i < len; i++) {
        if (got[i] != buf[i]) {
            return (int)i + 1;      /* first mismatching byte, 1-based so 0 means match */
        }
    }
    return 0;
}

int sx126x_send(const sx126x_cfg_t *c, const uint8_t *buf, uint8_t len, uint32_t timeout_ms,
                uint32_t *tx_cycles)
{
    int e;
    uint8_t p[3];
    uint8_t irq[2];
    uint32_t ticks, start, limit;

    if ((e = hal_wakeup()) != 0) return e;
    if ((e = set_packet_params(c, len)) != 0) return e;

    {
        const uint8_t wb[2] = { OP_WRITE_BUFFER, 0x00 };
        if ((e = hal_write(wb, sizeof wb, buf, len)) != 0) return e;
    }

    /* GUARDRAIL: clear the IRQ BEFORE SET_TX. DIO1 is a LEVEL, so a flag left over from a previous packet makes the
     * wait below exit instantly and the TX_DONE check then report NO_TXDONE - a failure that looks like a radio fault
     * and is really a missing clear (docs/28 §3.5). */
    p[0] = 0xFF; p[1] = 0xFF;
    if ((e = cmd(OP_CLEAR_IRQ_STATUS, p, 2)) != 0) return e;

    ticks = timeout_ms * 64u;                       /* 15.625 us per tick */
    if (ticks > 0xFFFFFFu) ticks = 0xFFFFFFu;
    p[0] = (uint8_t)(ticks >> 16); p[1] = (uint8_t)(ticks >> 8); p[2] = (uint8_t)ticks;
    if ((e = cmd(OP_SET_TX, p, 3)) != 0) return e;

    /* Bound the wait in cycles (17.5 MHz), not in poll counts, and keep the elapsed count: it is the air time. */
    start = ULP_RISCV_GET_CCOUNT();
    limit = timeout_ms * 17500u;
    while (!hal_dio1()) {
        if ((uint32_t)(ULP_RISCV_GET_CCOUNT() - start) > limit) return SX126X_ERR_TIMEOUT;
    }

    if (tx_cycles != 0) {
        /* GUARDRAIL: ULP_RISCV_GET_CCOUNT() yields a SIGNED int, and the counter is 32 bits (245 s at 17.5 MHz). A
         * plain unsigned end-start is correct only if no wrap happened; measured, it produced 3.4e9 cycles (194 s of
         * "air time") for a ~108 ms packet, which is a wrap read as a huge positive. Subtract as signed, then cast. */
        *tx_cycles = (uint32_t)((int32_t)ULP_RISCV_GET_CCOUNT() - (int32_t)start);
    }

    {
        const uint8_t rq[2] = { OP_GET_IRQ_STATUS, 0x00 };
        if ((e = hal_read(rq, sizeof rq, irq, sizeof irq)) != 0) return e;
    }
    p[0] = 0xFF; p[1] = 0xFF;
    (void)cmd(OP_CLEAR_IRQ_STATUS, p, 2);

    if (!(((uint16_t)irq[0] << 8 | irq[1]) & IRQ_TX_DONE)) {
        return SX126X_ERR_NO_TXDONE;
    }
    return 0;
}

int sx126x_sleep(int warm)
{
    /* bit 2 = 1: warm start, configuration retained */
    return cmd1(OP_SET_SLEEP, warm ? 0x04 : 0x00);
}
