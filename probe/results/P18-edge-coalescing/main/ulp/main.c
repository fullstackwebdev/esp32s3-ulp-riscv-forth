/* P18 — ULP side: timer-only wakes, sample the RTC-IO interrupt latch for GPIO4, clear it.
 *
 * The whole question of the probe lives in three lines: read RTCIO STATUS while the HP-driven
 * edge is asleep-visible, record whether GPIO4's bit is set, and clear it so the next wake can
 * prove the latch went clean.  The ULP is armed on the RTC timer ONLY (no GPIO wakeup), so an
 * edge never wakes us — a wake only ever *reports* what latched since the previous wake.
 */
typedef unsigned int u32;

/* GUARDRAIL: the ULP core sees the RTC peripherals at 0x8000/0xA400-based addresses, not the
 * HP's 0x6000_8400 alias (P16 measured RTCIO at 0xA400 from the ULP, and a HP-address write
 * from the ULP is a silent no-op).  RTCIO: OUT_W1TS +0x04, OUT_W1TC +0x08, STATUS +0x18,
 * STATUS_W1TC +0x20, IN +0x24, PIN4 +0x38. */
#define RTCIO_STATUS       0xA418u
#define RTCIO_STATUS_W1TC  0xA420u
#define RTCIO_IN           0xA424u
/* GUARDRAIL: RTCIO data/status bits start at bit 10 (RTC GPIO0 = bit 10), so GPIO4 is bit 14.
 * Writing BIT(4) here clears pin 214-never and the latch silently survives every "clear". */
#define RTCIO_GPIO4_BIT    (1u << 14)

#define RING 64

/* Single-writer rule (P06 wedge): every word below is written by this core and only read by
 * the HP.  Nothing here is ever written by the HP while the timer may be running. */
volatile u32 wake_count;      /* incremented AFTER the status sample */
volatile u32 ev_count;        /* wakes that found GPIO4's latch set */
volatile u32 last_status;     /* raw RTCIO STATUS word, bits [31:10] */
volatile u32 last_in;         /* raw RTCIO IN word: pad level as the RTC domain sees it */
volatile u32 period_cyc;      /* ULP cycles since the previous wake */
volatile u32 prev_cyc;
volatile u32 statuses[RING];
volatile u32 cycles[RING];

static u32 rdcyc(void)
{
    u32 c;
    __asm__ volatile ("rdcycle %0" : "=r"(c));
    return c;
}

int main(void)
{
    u32 idx = wake_count & (u32)(RING - 1u);
    u32 cyc = rdcyc();
    u32 st  = *(volatile u32 *)RTCIO_STATUS;
    u32 inv = *(volatile u32 *)RTCIO_IN;
    u32 hit = (st & RTCIO_GPIO4_BIT) ? 1u : 0u;

    /* GUARDRAIL: sample BEFORE publishing wake_count, never after.  The HP timestamps an edge
     * when it observes wake_count change; if the counter moved first, an edge driven in reply
     * could be swallowed by this wake's own status read and the measured latency would be
     * sub-microsecond nonsense instead of "the next wake saw it". */
    statuses[idx] = hit;
    period_cyc = cyc - prev_cyc;
    prev_cyc = cyc;
    cycles[idx] = period_cyc;
    last_status = st;
    last_in = inv;
    if (hit) {
        ev_count = ev_count + 1u;
        /* Clear only GPIO4's bit through W1TC: writing the whole STATUS word would also drop
         * another pin's pending latch, and the ring's contract is one event per pin per wake. */
        *(volatile u32 *)RTCIO_STATUS_W1TC = RTCIO_GPIO4_BIT;
    }
    wake_count = wake_count + 1u;
    return 0;
}
