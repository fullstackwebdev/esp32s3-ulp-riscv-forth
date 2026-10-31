/* P16 — ULP-RISC-V page-fetch client.
 *
 * The ULP is the *client*: it issues a 512 B page read request into the shared RTC-slow
 * mailbox, waits for the HP server to answer, and stamps the round trip with rdcycle.
 * Every latency in RESULT.md comes from deltas[] below, so the log is enough to recompute
 * the distribution.
 *
 * mode 0 : HP awake, busy-polling the request slot.
 * mode 1 : HP awake, blocked on a GPIO doorbell driven by this core (RTCIO write).
 * mode 2 : one deliberately faulted request, selected by fcase (1..4).
 *
 * GUARDRAIL: all shared words are written by one side only — req_* by the ULP, rsp_* by the
 * HP, mode/fcase/n_iter/fault_inject by the HP while the ULP is stopped.  P06 wedged the
 * board for hours by touching COCPU_* from the HP mid-wake; the same rule applies to any
 * word the ULP may be reading: the HP only pokes it after ulp_riscv_timer_stop().
 */
typedef unsigned int u32;
typedef unsigned char u8;

#define ST_OK      0
#define ST_TIMEOUT 1   /* no answer from the server inside the cycle cap */
#define ST_BADCHK  2   /* checksum over the page did not match rsp_chk */
#define ST_RANGE   3   /* server rejected the address, no page copied */
#define ST_STALE   4   /* a page arrived but it is not the page we asked for */
#define ST_DUAL    5   /* two requests in flight: answer for seq N carried page N+1 */

/* 3e6 cycles ~= 158 ms at the measured 19 MHz.  Bounded so a stopped server is a named
 * timeout instead of a hang — the same bounded-poll rule the HP side uses. */
#define TMO_CYCLES 3000000u
/* Per-fetch cap for the A/B loops: a missing doorbell costs 10 ms per iteration, so a
 * dead signal shows up as 200 named timeouts in ~2 s instead of 31 s (which would blow the
 * HP phase budget and lose the pass). */
#define TMO_ITER   200000u
#define MAXIT 200

volatile u32 mode;
volatile u32 fcase;
volatile u32 n_iter;
volatile u32 req_seq;
volatile u32 req_addr;
volatile u32 rsp_seq;
volatile u32 rsp_status;
volatile u32 rsp_chk;
volatile u32 phase_done;
volatile u32 f_seq_seen;
volatile u32 f_marker;
volatile u32 f_status;

u32 deltas[MAXIT];
u8  statii[MAXIT];
u8  page[512];

/* RTCIO window seen from the ULP core.  GUARDRAIL: the ULP sees the RTC peripherals at
 * 0x8000-based offsets (RTCCNTL 0x8000, RTCIO 0xA400), not the HP 0x6009_xxxx alias — a
 * wrong alias silently reads RTC slow RAM and yields fake register values (P05 bug class).
 * GPIO4 (bit 4) = RTC_GPIO_OUT_W1TS/ENABLE_W1TS: not USB, not strapping, not UART0. */
#define RTCIO_OUT_W1TS     0xA404u
#define RTCIO_OUT_W1TC     0xA408u
#define RTCIO_ENABLE_W1TS  0xA410u
#define RTCIO_ENABLE_W1TC  0xA414u
#define DOORBELL_BIT       (1u << 4)

static u32 rdcyc(void)
{
    u32 c;
    __asm__ volatile ("rdcycle %0" : "=r"(c));
    return c;
}

/* 32-bit rotating XOR over the 128 words of the page.  Cheap enough for the ULP (a real
 * CRC32 over 512 B would cost more than the fetch it is validating) and it still catches
 * a single flipped word, which is what the bad-CRC failure mode injects. */
static u32 chk512(void)
{
    u32 a = 0;
    volatile u32 *p = (volatile u32 *)page;
    for (u32 i = 0; i < 128u; i++) {
        a = (a << 1) | (a >> 31);
        a ^= p[i];
    }
    return a;
}

/* One request/response round trip.  Returns the elapsed cycles (0 = timed out). */
static u32 fetch(u32 seq, u32 addr, u32 doorbell, u32 tmo)
{
    u32 t0, t1;
    req_addr = addr;
    t0 = rdcyc();
    req_seq = seq;
    if (doorbell) {
        *(volatile u32 *)RTCIO_ENABLE_W1TS = DOORBELL_BIT;
        *(volatile u32 *)RTCIO_OUT_W1TS = DOORBELL_BIT;
    }
    for (;;) {
        if (rsp_seq == seq) {
            t1 = rdcyc();
            break;
        }
        t1 = rdcyc();
        if (t1 - t0 > tmo) {
            t1 = 0;
            break;
        }
    }
    if (doorbell) {
        *(volatile u32 *)RTCIO_OUT_W1TC = DOORBELL_BIT;
    }
    return t1 ? (t1 - t0) : 0;
}

static u32 classify(u32 want_page)
{
    if (rsp_status == 2u) {
        return ST_RANGE;
    }
    if (chk512() != rsp_chk) {
        return ST_BADCHK;
    }
    if ((u32)page[0] != want_page) {
        return ST_STALE;
    }
    return ST_OK;
}

int main(void)
{
    u32 i;

    if (mode == 0u || mode == 1u) {
        u32 doorbell = (mode == 1u) ? 1u : 0u;
        u32 n = (n_iter > MAXIT) ? MAXIT : n_iter;
        for (i = 0; i < n; i++) {
            u32 pg = i % 4u;                     /* P19: frames fixed at 4 x 512 */
            u32 d = fetch(i + 1u, pg * 512u, doorbell, TMO_ITER);
            deltas[i] = d;
            statii[i] = d ? (u8)classify(pg) : (u8)ST_TIMEOUT;
        }
        if (doorbell) {
            *(volatile u32 *)RTCIO_ENABLE_W1TC = DOORBELL_BIT;
        }
        phase_done = 1u;
        return 0;
    }

    /* ---- failure modes: exactly one deliberate defect per pass ---- */
    if (fcase == 1u) {                       /* server stopped */
        u32 d = fetch(10u, 0u, 0u, TMO_CYCLES);
        f_seq_seen = rsp_seq;
        f_status = d ? (u32)classify(0u) : (u32)ST_TIMEOUT;
    } else if (fcase == 2u) {                /* corrupted checksum */
        u32 d = fetch(11u, 0u, 0u, TMO_CYCLES);
        f_seq_seen = rsp_seq;
        f_status = d ? (u32)classify(0u) : (u32)ST_TIMEOUT;
    } else if (fcase == 3u) {                /* address outside the window */
        u32 d = fetch(12u, 0x100000u, 0u, TMO_CYCLES);
        f_seq_seen = rsp_seq;
        f_status = d ? (u32)classify(0u) : (u32)ST_TIMEOUT;
    } else {                                  /* two requests in flight */
        u32 t0, t1;
        req_addr = 0u;
        req_seq = 1u;
        req_addr = 512u;                      /* second request before the first is answered */
        req_seq = 2u;
        t0 = rdcyc();
        while (rsp_seq == 0u || rsp_seq == 2u) {
            t1 = rdcyc();
            if (t1 - t0 > TMO_CYCLES) {
                break;
            }
        }
        f_seq_seen = rsp_seq;
        f_marker = (u32)page[0];
        /* Two defects are possible and both are corruption: the first answer is swallowed
         * entirely (rsp_seq jumped to 2), or seq 1 answered with page 1's bytes because the
         * HP re-read req_addr mid-service.  Only "seq 1 answered with page 0" is clean. */
        if (rsp_seq == 2u) {
            f_status = ST_DUAL;
        } else if (rsp_seq == 1u && f_marker == 1u) {
            f_status = ST_DUAL;
        } else if (rsp_seq == 1u) {
            f_status = classify(0u);
        } else {
            f_status = ST_TIMEOUT;
        }
    }
    phase_done = 1u;
    return 0;
}
