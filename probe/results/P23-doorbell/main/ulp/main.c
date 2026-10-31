/* P23 — ULP client: 200 page requests, signalled to the HP with RTC_CNTL_SW_CPU_INT.
 *
 * One loop, four HP-side configurations:
 *   mode 0 : no doorbell at all (polling control, HP busy-waits)
 *   mode 1 : doorbell, HP awake and blocked on the RTC COCPU ISR      (path 1)
 *   mode 2 : doorbell, HP in light sleep                              (path 2)
 *   mode 3 : doorbell, HP in deep sleep (boots on every wake)         (path 3)
 *
 * GUARDRAIL: the doorbell is `ulp_riscv_wakeup_main_processor()` (SW_CPU_INT ->
 * RTC_CNTL_COCPU_INT_ST), NOT the RTCIO GPIO pad P16 tried.  P16 drove GPIO4 from RTCIO in
 * both muxes and measured isr_count=0 over 200 edges; the pad path costs a whole run to
 * disprove, the documented call costs one line.  Use the call.
 *
 * GUARDRAIL: never write a COCPU_STAR / mailbox word the ULP may be reading — P06 wedged the
 * board that way.  Every shared word here has exactly one writer: req_STAR / deltas / statii by
 * this core, everything else by the HP while the ULP timer is stopped.
 */
typedef unsigned int u32;
typedef unsigned char u8;

/* Declared by hand rather than including ulp_riscv_utils.h: the ULP build links that
 * translation unit anyway, and the raw prototype keeps this file free of HP headers. */
extern void ulp_riscv_wakeup_main_processor(void);

#define ST_OK      0
#define ST_TIMEOUT 1   /* no answer from the server inside the cycle cap */
#define ST_BADCHK  2   /* checksum over the page did not match rsp_chk */
#define ST_STALE   3   /* a page arrived but it is not the page we asked for */

/* 200 000 cycles ~ 10.5 ms at the measured 19 MHz: a dead doorbell shows up as 200 named
 * timeouts in ~2 s instead of blowing the HP phase budget. */
#define TMO_AWAKE 200000u
/* One deep-sleep wake boots the whole HP (~250 ms), so that cap has to be seconds. */
#define TMO_DEEP  40000000u
#define MAXIT 200

volatile u32 mode;
volatile u32 n_iter;
volatile u32 req_seq;
volatile u32 req_addr;
volatile u32 rsp_seq;
volatile u32 rsp_status;
volatile u32 rsp_chk;
volatile u32 phase_done;
volatile u32 iters_done;

u32 deltas[MAXIT];
u8  statii[MAXIT];
u8  page[512];

static u32 rdcyc(void)
{
    u32 c;
    __asm__ volatile ("rdcycle %0" : "=r"(c));
    return c;
}

/* 32-bit rotating XOR over the 128 words of the page (same as P16: a real CRC32 over 512 B
 * costs more than the fetch it validates and still catches a single flipped word). */
/* GUARDRAIL: ulp_riscv_delay_cycles() is a test-app helper, not part of the ULP core
 * library — referencing it is an undefined reference at ULP link time.  Spin on rdcycle. */
static void delay_cycles(u32 cycles)
{
    u32 t0 = rdcyc();
    while (rdcyc() - t0 < cycles) {
    }
}

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

static u32 classify(u32 want_page)
{
    if (rsp_status == 2u) {
        return ST_STALE;                 /* rejected: no page copied */
    }
    if (chk512() != rsp_chk) {
        return ST_BADCHK;
    }
    if ((u32)page[0] != want_page) {
        return ST_STALE;
    }
    return ST_OK;
}

/* One request/response round trip; returns elapsed cycles, 0 = timed out.
 * GUARDRAIL: req_addr before req_seq, and the wake call after req_seq — the doorbell is
 * the only ordering guarantee the HP gets, so the request must be complete before it. */
static u32 fetch(u32 seq, u32 addr, u32 doorbell, u32 tmo)
{
    u32 t0, t1;
    req_addr = addr;
    t0 = rdcyc();
    req_seq = seq;
    if (doorbell) {
        ulp_riscv_wakeup_main_processor();
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
    return t1 ? (t1 - t0) : 0;
}

int main(void)
{
    u32 i, n, doorbell, tmo;
    u32 misses = 0;

    doorbell = (mode == 0u) ? 0u : 1u;
    tmo = (mode == 3u) ? TMO_DEEP : TMO_AWAKE;
    n = (n_iter > MAXIT) ? MAXIT : n_iter;

    /* GUARDRAIL: in mode 2 the HP has to be *in* light sleep before the first request, or
     * iteration 1 is lost to the sleep-entry race (~1 ms) and reads as a dead signal.
     * 190 000 cycles ~ 10 ms buys the entry. */
    if (mode == 2u) {
        delay_cycles(190000u);
    }

    for (i = 0; i < n; i++) {
        u32 pg = i % 4u;                     /* P19: frames fixed at 4 x 512 */
        u32 d = fetch(i + 1u, pg * 512u, doorbell, tmo);
        deltas[i] = d;
        statii[i] = d ? (u8)classify(pg) : (u8)ST_TIMEOUT;
        iters_done = i + 1u;
        /* Bail after three dead round trips: the signal path is broken, and 197 more 10 ms
         * timeouts would only spend the capture window without adding information. */
        if (!d && ++misses >= 3u) {
            break;
        }
        if (d) {
            misses = 0;
        }
    }
    phase_done = 1u;
    return 0;
}
