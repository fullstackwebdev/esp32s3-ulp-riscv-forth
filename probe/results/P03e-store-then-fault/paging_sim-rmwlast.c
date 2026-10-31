/* paging_sim.c — P03: host model of the fault -> retire -> retry paging protocol.
 *
 * Build: gcc -DHOST -DPAGING -std=c99 -O1 -Wall -Wextra -o paging_sim paging_sim.c
 *
 * The engine (uforth.c, PAGING build) reaches memory only through vm_rd8/vm_wr8/vm_rd16/
 * vm_rd32/vm_wr16/vm_wr32/vm_touch. Each of those resolves the containing 512 B page; a
 * miss longjmps out of the interpreter to the retry driver, which loads the page from the
 * fake server and re-enters the *same* primitive dispatch.
 *
 * Address space
 *   [0x00000000, 0x00010000)  16-bit dictionary window -> aliases flash pages 0..127
 *                             (tokens are u16 offsets, so the dictionary must be reachable
 *                             in 16 bits — see P02)
 *   [0x10000000, +1 MB)       "PSRAM": flat, always resident
 *   [0x20000000, +1 MB)       "flash": pageable, backed by the fake byte server
 *   anything else             fault with kind BADADDR (loud, never silently ignored)
 */
#define _POSIX_C_SOURCE 199309L
#define main uforth_unused_main
#include "uforth.c"
#undef main

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include <time.h>

#define PAGE_SIZE   512
#define MAX_FRAMES  8
#define PSRAM_BASE  0x10000000u
#define PSRAM_SIZE  (1u << 20)
#define FLASH_BASE  0x20000000u
#define FLASH_SIZE  (1u << 20)
#define PAGES       (FLASH_SIZE / PAGE_SIZE)
#define DICT_WINDOW 0x10000u

enum { VM_FAULT_MISS = 1, VM_FAULT_BAD = 2 };
/* GUARDRAIL: P03 reported `err=1`/`err=99` with no name, so a livelock and a bad address
 * looked identical in the log — every failure path must carry a name the report can quote. */
enum { PROBE_OK = 0, PROBE_ERR = 1, PROBE_ERR_FAULT_LOOP = 2, PROBE_ERR_NO_CKPT = 3, PROBE_ERR_RETRY_CAP = 4 };
#define RETRY_CAP 200             /* per run()/feed(): a non-converging retry is an error, not a hang */
static const char *err_name(int e)
{
    switch (e) {
    case PROBE_OK:               return "OK";
    case PROBE_ERR:              return "ERR";
    case PROBE_ERR_FAULT_LOOP:   return "ERR_PAGE_FAULT_LOOP";
    case PROBE_ERR_NO_CKPT:      return "ERR_NO_RESTART_CKPT";
    case PROBE_ERR_RETRY_CAP:    return "ERR_RETRY_CAP";
    default:                     return "ERR_UNKNOWN";
    }
}
#define WAKE_DISPATCHES 64        /* one "wake" = one scheduled slice, in primitive dispatches */

static u8 *psram;
static u8 *flash_store;                  /* the server's copy: reachable only via a frame */

static u8  frame_mem[MAX_FRAMES][PAGE_SIZE];
static i32 frame_page[MAX_FRAMES];
static u8  frame_dirty[MAX_FRAMES];
static u8  frame_pinned[MAX_FRAMES];
static u32 frame_used[MAX_FRAMES];
static int nframes = 4;
static u32 lru_clock;

/* pin set for the definition currently executing / compiling */
static i32 pin_pages[2];
static int npins, pin_cap = 2;
static int exec_depth;

/* ERR_HOT_SET detector state */
static u32 faults_wake, faults_prev_wake;
static int hot_streak;

static void feed(const char *s);
static void memory_reset(void);
static int  pin_holds(int f);

static struct stats {
    unsigned long hits, faults, spurious, loads, writebacks, bad_addr, no_victim, hot_set;
    unsigned long dispatches, retries, resume_mismatch, no_access_positions;
    unsigned long loads_forced_evict, perm_faults;
    unsigned long latency_units;
    unsigned long peak_fpw;
    int err;
} st;

/* counters reset per case */
static void stats_reset(void)
{
    memset(&st, 0, sizeof st);
    faults_wake = faults_prev_wake = 0;
    hot_streak = 0;
}

/* ---- output buffer: rolled back when a dispatch faults (an EMIT must not repeat) ---- */
static char outbuf[65536];
static u32 outlen;

char probe_out[65536];
u32  probe_outlen;
/* token last fetched by run_from; written by uforth.c, read by the checkpoint trace only */
u32 vm_dbg_cf;

/* ---- P03c checkpoint trace: EVERY checkpoint, not just the faults ----
 * GUARDRAIL: P03b logged faults only, so the two runs could not be diffed line by line and the
 * cause had to be guessed from the digest. Both runs now emit one line per checkpoint to their
 * own file, same build, differing only in `inject_at`. */
static FILE *tlog;
static int trace_on;
/* GUARDRAIL: the prelude also dispatches (it compiles boot_min.fs), so an ungated trace hides
 * the measured window in ~2000 prelude lines — trace only after the counters are reset. */
static int trace_meas;

static void out_truncate(u32 n) { if (n < outlen) outlen = n; }

int  pl_key(void)   { return 4; }         /* never blocking; workloads do not read keys */
void pl_emit(int c) { if (outlen < sizeof outbuf) outbuf[outlen++] = (char)c; }

/* ---- address space ---- */
static i32 flash_page(u32 va)
{
    if (va < DICT_WINDOW) return (i32)(va >> 9);
    if (va >= FLASH_BASE && va < FLASH_BASE + FLASH_SIZE) return (i32)((va - FLASH_BASE) >> 9);
    return -1;
}
static int in_psram(u32 va) { return va >= PSRAM_BASE && va < PSRAM_BASE + PSRAM_SIZE; }

static int find_frame(i32 pg)
{
    int f;
    for (f = 0; f < nframes; f++) if (frame_page[f] == pg) return f;
    return -1;
}

/* a definition may pin at most min(2, nframes/2) code pages, always leaving a victim — a
 * pin set that fills every frame turns the first fault into a false ERR_HOT_SET */
static void pin_page(i32 pg)
{
    int i;
    if (npins >= pin_cap) return;
    for (i = 0; i < npins; i++) if (pin_pages[i] == pg) return;
    pin_pages[npins++] = pg;
}

/* ---- fault raising ---- */
static jmp_buf vm_jb;
static u32 vm_fault_addr;
static int vm_fault_kind;
static int vm_spurious_armed, vm_spurious_fired, vm_armed_from_prev;

/* permanent-fault proof: after dispatch `perm_at`, one page is *permanently* absent —
 * the server load lands it and the next resolve still faults on it. That is the state the
 * progress bound exists for: same (w, ip, p) faulting with no dispatch retiring in between. */
static u32 perm_at;
static int perm_arm_next, perm_active;
static i32 perm_pg = -1;

/* one line per fault, to a file: P03 lost its hang position because the counters were only
 * printed on a mismatch — never again. */
static FILE *flog;
static void log_fault(const char *where, u32 w, u32 ip, u32 p, u32 addr, unsigned long retry)
{
    if (tlog && trace_on && trace_meas)
        fprintf(tlog, "FAULT-%s d=%lu w=%u ip=%u p=%u addr=%u retry=%lu sp=%u rsp=%u\n",
                where, st.dispatches, w, ip, p, addr, retry, (unsigned)sp, (unsigned)rsp);
    if (!flog) return;
    fprintf(flog, "%s w=%u ip=%u p=%u addr=%u retry=%lu perm=%d\n",
            where, w, ip, p, addr, retry, perm_active);
    fflush(flog);
}

static void raise_fault(u32 va, int kind)
{
    vm_fault_addr = va; vm_fault_kind = kind;
    longjmp(vm_jb, kind);
}

/* resolve one byte; returns a pointer into the frame, or faults */
static u8 *resolve(u32 va)
{
    i32 pg; int f;
    if (in_psram(va)) { st.hits++; return psram + (va - PSRAM_BASE); }
    pg = flash_page(va);
    if (pg < 0) { st.bad_addr++; raise_fault(va, VM_FAULT_BAD); }
    /* GUARDRAIL: the injected fault must fire even when the page is resident. P03 armed it
     * after the hit path, so injections at resident positions silently did nothing and read
     * as "no mismatch". Armed here, and an unpinned resident frame is written back + evicted
     * so the retry really does pay a page fetch instead of re-reading a warm frame. */
    if (vm_spurious_armed) {
        vm_spurious_armed = 0; vm_spurious_fired = 1;
        st.spurious++;
        f = find_frame(pg);
        /* GUARDRAIL: NOEVICT=1 keeps the spurious fault with the page still resident. It is the
         * control run for the forced eviction: if only the evicting variant mismatches, the
         * mismatch is the eviction cascade, not the retry. Without this control the probe
         * would blame the resume point for a harness artifact. */
        if (f >= 0 && !pin_holds(f) && !getenv("NOEVICT")) {
            if (frame_dirty[f]) {
                memcpy(flash_store + (u32)pg * PAGE_SIZE, frame_mem[f], PAGE_SIZE);
                st.writebacks++;
            }
            frame_page[f] = -1; frame_dirty[f] = 0; frame_used[f] = 0;
            st.loads_forced_evict++;
        }
        raise_fault(va, VM_FAULT_MISS);
    }
    if (perm_arm_next) { perm_arm_next = 0; perm_active = 1; perm_pg = pg; }
    if (perm_active && pg == perm_pg) {                 /* page never becomes usable */
        st.perm_faults++;
        raise_fault(va, VM_FAULT_MISS);
    }
    f = find_frame(pg);
    if (f >= 0) {
        st.hits++;
        frame_used[f] = ++lru_clock;
        if (va < DICT_WINDOW) pin_page(pg);          /* code pages of the running definition */
        return &frame_mem[f][va & (PAGE_SIZE - 1)];
    }
    st.faults++;
    raise_fault(va, VM_FAULT_MISS);
    return 0;                       /* not reached: raise_fault longjmps */
}
/* resident pointer, no resolve: only legal after vm_touch() covered the range */
static u8 *located(u32 va)
{
    i32 pg; int f;
    if (in_psram(va)) return psram + (va - PSRAM_BASE);
    pg = flash_page(va);
    f = find_frame(pg);
    if (f < 0) { st.bad_addr++; raise_fault(va, VM_FAULT_BAD); }   /* unreachable if touched */
    return &frame_mem[f][va & (PAGE_SIZE - 1)];
}
static void dirty(u32 va)
{
    i32 pg = flash_page(va); int f;
    if (pg < 0) return;
    f = find_frame(pg);
    if (f >= 0) frame_dirty[f] = 1;
}

void vm_touch(u32 va, u32 len)
{
    u32 i;
    for (i = 0; i < len; i++) (void)resolve(va + i);
}
static int trace_sys;
u8   vm_rd8(u32 va)            { return *resolve(va); }
void vm_wr8(u32 va, u8 v)      { if (trace_sys && va < 24) printf("  wr8[%u]=%u\n", va, v); *(resolve(va)) = v; dirty(va); }
static u16 rd16_located(u32 va) { return (u16)(*located(va) | (u16)*located(va + 1) << 8); }
u16  vm_rd16(u32 va)           { vm_touch(va, 2); return rd16_located(va); }
u32  vm_rd32(u32 va)           { vm_touch(va, 4); return (u32)rd16_located(va) | (u32)rd16_located(va + 2) << 16; }
void vm_wr16(u32 va, u16 v)    { if (trace_sys && va < 24) printf("  wr16[%u]=%u\n", va, v); vm_touch(va, 2); *located(va) = (u8)v; *located(va + 1) = (u8)(v >> 8); dirty(va); dirty(va + 1); }
void vm_wr32(u32 va, u32 v)    { if (trace_sys && va < 24) printf("  wr32[%u]=%u\n", va, v); vm_touch(va, 4); *located(va) = (u8)v; *located(va + 1) = (u8)(v >> 8);
                                 *located(va + 2) = (u8)(v >> 16); *located(va + 3) = (u8)(v >> 24);
                                 dirty(va); dirty(va + 3);  }

/* ---- dispatch checkpoints: the restartable-primitive mechanism ----
 * GUARDRAIL: the stacks are restored on a fault, not left half-popped — without this a
 * fault inside `!` (which pops addr to resolve it) drops the caller's operands and every
 * retry computes a different answer. Saved per dispatch, 3 windows per dispatch. */
static struct {
    u16 w, ip, p; u8 sp, rsp; u32 ds[SD], rs[SD]; u32 outlen; int valid;
} ck;

/* progress bound: the key of the last checkpoint that faulted, and how many times it has
 * faulted without any other dispatch window being started in between. K = 2 per P03's rule. */
static u16 loop_w, loop_ip, loop_p;
static int loop_seen, loop_count;
#define LOOP_K 2

static void ckpt_save(u32 w, u32 ip, u32 p)
{
    int i;
    /* GUARDRAIL: reaching a *different* window is the only proof of progress. A retry that
     * re-enters the same (w, ip, p) and faults again has advanced nothing, and P03's 4e6-retry
     * guard turned that into a 100 s "hang" with no position — clear the key only here. */
    if (loop_seen && ((u16)w != loop_w || (u16)ip != loop_ip || (u16)p != loop_p)) {
        loop_seen = 0; loop_count = 0;
    }
    ck.w = (u16)w; ck.ip = (u16)ip; ck.p = (u16)p;
    ck.sp = sp; ck.rsp = rsp;
    memcpy(ck.ds, ds, sizeof ds); memcpy(ck.rs, rs, sizeof rs);
    ck.outlen = outlen; ck.valid = 1;
    /* GUARDRAIL: log the stacks *with* the triple — a mismatch in (w, ip, p) alone cannot show
     * that a dispatch re-executed with the stack already advanced. Keep the arrays short so the
     * baseline and the retried run stay diffable. */
    if (tlog && trace_on && trace_meas) {
        fprintf(tlog, "CK d=%lu w=%u ip=%u p=%u cf=%u sp=%u rsp=%u ds=",
                st.dispatches, (unsigned)w, (unsigned)ip, (unsigned)p,
                (unsigned)vm_dbg_cf, (unsigned)sp, (unsigned)rsp);
        for (i = 0; i < (int)sp && i < 4; i++) fprintf(tlog, "%u,", (unsigned)ds[i]);
        fprintf(tlog, " rs=");
        for (i = 0; i < (int)rsp && i < 4; i++) fprintf(tlog, "%u,", (unsigned)rs[i]);
        fprintf(tlog, " olen=%u\n", outlen);
    }
}
void vm_ckpt_fetch(u32 w, u32 ip, u32 p)    { ckpt_save(w, ip, p); }
void vm_ckpt_dispatch(u32 w, u32 ip, u32 p) { ckpt_save(w, ip, p); }
void vm_ckpt_next(u32 w, u32 ip, u32 p)     { ckpt_save(w, ip, p); }

static u32 rd32_now(u32 a) { return vm_rd32(a); }
static u16 first_w, first_ip, first_p; static int first_fault_seen;

/* interpret-level restart point: before each word is parsed (see interpret() in uforth.c) */
static struct {
    u8 ti, sp, rsp; u32 ds[SD], rs[SD]; u32 here, latest, state, outlen; int valid;
} ip_ck;

void vm_ckpt_interp(void)
{
    ip_ck.ti = ti; ip_ck.sp = sp; ip_ck.rsp = rsp;
    memcpy(ip_ck.ds, ds, sizeof ds); memcpy(ip_ck.rs, rs, sizeof rs);
    ip_ck.here = rd32_now(V_HERE); ip_ck.latest = rd32_now(V_LATEST); ip_ck.state = rd32_now(V_STATE);
    ip_ck.outlen = outlen; ip_ck.valid = 1;
}

/* ---- pinning: the definition being executed/compiled keeps its code pages ---- */
static void pin_reset_pins(void) { npins = 0; }
void vm_hook_docol(void) { if (exec_depth++ == 0) pin_reset_pins(); }
void vm_hook_exit(void)  { if (exec_depth > 0 && --exec_depth == 0) pin_reset_pins(); }
void vm_hook_colon(void) { pin_reset_pins(); }
void vm_hook_semi(void)  { pin_reset_pins(); }

/* ---- fault injection: force exactly one fault per position ---- */
static long inject_at;          /* 0 = off; else the global dispatch index to fault */

void vm_on_dispatch(void)
{
    st.dispatches++;
    if (vm_armed_from_prev && !vm_spurious_fired) st.no_access_positions++;
    vm_armed_from_prev = 0; vm_spurious_fired = 0; vm_spurious_armed = 0;
    if (inject_at > 0 && (long)st.dispatches == inject_at) {
        vm_spurious_armed = 1; vm_armed_from_prev = 1;
    }
    if (perm_at > 0 && (long)st.dispatches == (long)perm_at) perm_arm_next = 1;
    if (st.dispatches % WAKE_DISPATCHES == 0) {
        faults_prev_wake = faults_wake; faults_wake = 0;
        if (faults_prev_wake > st.peak_fpw) st.peak_fpw = faults_prev_wake;
        if (faults_prev_wake > (u32)nframes) { if (++hot_streak >= 2) st.hot_set = 1; }
        else hot_streak = 0;
    }
}

/* ---- frame table + fake server ---- */
static int pin_holds(int f)
{
    int i;
    for (i = 0; i < npins; i++) if (pin_pages[i] == frame_page[f]) return 1;
    return 0;
}
static int pick_victim(void)
{
    int f, best = -1;
    for (f = 0; f < nframes; f++) if (frame_page[f] < 0) return f;
    for (f = 0; f < nframes; f++) {
        if (pin_holds(f)) continue;
        if (best < 0 || frame_used[f] < frame_used[best]) best = f;
    }
    return best;
}
#define SERVER_LATENCY 8         /* simulated units of server work per page load (not instant) */

static int service_fault(void)
{
    i32 pg;
    int v;
    faults_wake++;
    if (vm_fault_kind == VM_FAULT_BAD) { st.err = 1; return -1; }
    pg = flash_page(vm_fault_addr);
    if (find_frame(pg) >= 0) return 0;                 /* spurious fault */
    v = pick_victim();
    if (v < 0) { st.no_victim++; st.hot_set = 1; st.err = 1; return -1; }
    if (frame_page[v] >= 0 && frame_dirty[v]) {
        memcpy(flash_store + (u32)frame_page[v] * PAGE_SIZE, frame_mem[v], PAGE_SIZE);
        st.writebacks++;
    }
    memcpy(frame_mem[v], flash_store + (u32)pg * PAGE_SIZE, PAGE_SIZE);
    frame_page[v] = pg; frame_dirty[v] = 0; frame_used[v] = ++lru_clock;
    st.loads++;
    st.latency_units += SERVER_LATENCY;
    st.dispatches += SERVER_LATENCY;                   /* the stall costs budget slots */
    return 0;
}

/* ---- the retry driver: the only way the engine runs in this build ---- */
static u16 fault_w, fault_ip, fault_p;
static u16 r_w, r_ip, r_p;   /* GUARDRAIL: cursor kept out of locals — a longjmp out of the
                                interpreter may clobber a local modified after setjmp */
static void run(u16 w)
{
    static u32 guard;
    static jmp_buf saved;
    /* GUARDRAIL: a fault raised by the outer interpreter resolves against vm_jb, so run()
     * must put the caller's buffer back on every exit — otherwise find() faults into a
     * long-dead frame ("longjmp causes uninitialized stack frame"). */
    memcpy(&saved, &vm_jb, sizeof vm_jb);
    guard = 0; r_w = w; r_ip = 0; r_p = 0;
    loop_seen = 0; loop_count = 0;
    for (;;) {
        if (setjmp(vm_jb) == 0) { (void)run_from(r_w, r_ip, r_p); memcpy(&vm_jb, &saved, sizeof vm_jb); return; }
        st.retries++;
        if (!ck.valid) { st.err = PROBE_ERR_NO_CKPT; memcpy(&vm_jb, &saved, sizeof vm_jb); return; }
        fault_w = ck.w; fault_ip = ck.ip; fault_p = ck.p;
        /* GUARDRAIL: record the *first* faulting window of a case, not the last — a cascade
         * re-fires several windows and the last one says nothing about where the injection hit. */
        if (!first_fault_seen) { first_fault_seen = 1; first_w = ck.w; first_ip = ck.ip; first_p = ck.p; }
        log_fault("FAULT", ck.w, ck.ip, ck.p, vm_fault_addr, st.retries);
        /* GUARDRAIL: same window faulting twice with no window started in between is not
         * progress — it is the livelock. Abort *named*, do not spin to the retry cap: P03's
         * cap made a bounded loop look like a hang. */
        if (loop_seen && ck.w == loop_w && ck.ip == loop_ip && ck.p == loop_p) {
            if (++loop_count >= LOOP_K) {
                printf("ERR_PAGE_FAULT_LOOP w=%u ip=%u p=%u addr=%u retries=%lu\n",
                       ck.w, ck.ip, ck.p, vm_fault_addr, st.retries);
                st.err = PROBE_ERR_FAULT_LOOP;
                memcpy(&vm_jb, &saved, sizeof vm_jb);
                return;
            }
        } else {
            loop_w = ck.w; loop_ip = ck.ip; loop_p = ck.p;
            loop_seen = 1; loop_count = 0;
        }
        sp = ck.sp; rsp = ck.rsp;
        memcpy(ds, ck.ds, sizeof ds); memcpy(rs, ck.rs, sizeof rs);
        out_truncate(ck.outlen);
        /* the resume point must be the faulting primitive dispatch, not a token boundary */
        if (ck.w != r_w || ck.ip != r_ip) st.resume_mismatch++;
        r_w = ck.w; r_ip = ck.ip; r_p = ck.p;
        if (++guard > RETRY_CAP) {
            /* GUARDRAIL: P03's 4e6-retry cap was slower than the outer timeout, so a livelock
             * was recorded as a hang with no position. 200 retries per run() is already far
             * beyond any legitimate retry, and the cap is a *named* error. */
            printf("ERR_RETRY_CAP w=%u ip=%u p=%u addr=%u retries=%lu\n",
                   ck.w, ck.ip, ck.p, vm_fault_addr, st.retries);
            st.err = PROBE_ERR_RETRY_CAP;
            memcpy(&vm_jb, &saved, sizeof vm_jb);
            return;
        }
        if (service_fault()) { memcpy(&vm_jb, &saved, sizeof vm_jb); return; }
    }
}

/* ---- frame table setup, flush, checksum ---- */
static void vm_init(int frames)
{
    int f;
    nframes = frames;
    pin_cap = frames >= 4 ? 2 : 1;
    sp = rsp = 0; outlen = 0; lru_clock = 0;
    /* GUARDRAIL: the frame table must be marked empty *before* the dictionary is rebuilt —
     * a zeroed frame_page[] reads as "page 0 is resident" and then writes land in a frame
     * that was never loaded, which looks like correct paging until the checksum disagrees. */
    for (f = 0; f < MAX_FRAMES; f++) {
        frame_page[f] = -1; frame_dirty[f] = 0; frame_pinned[f] = 0; frame_used[f] = 0;
        memset(frame_mem[f], 0, PAGE_SIZE);
    }
    npins = 0; exec_depth = 0;
    /* GUARDRAIL: errf is the outer interpreter's sticky error flag and vm_init used to leave
     * it set — every case after one failed case then "failed in its prelude" and the sweep
     * reported positions it never ran. Reset all interpreter state here. */
    errf = 0;
    memory_reset();
    vm_armed_from_prev = vm_spurious_fired = vm_spurious_armed = 0;
    /* GUARDRAIL: the permanent-fault probe is per-case state; if perm_active survived
     * vm_init the *next* case would fault forever on a page it never asked for. */
    perm_arm_next = 0; perm_active = 0; perm_pg = -1;
    loop_seen = 0; loop_count = 0;
    stats_reset();
}

static void vm_flush(void)
{
    int f;
    for (f = 0; f < nframes; f++)
        if (frame_page[f] >= 0 && frame_dirty[f]) {
            memcpy(flash_store + (u32)frame_page[f] * PAGE_SIZE, frame_mem[f], PAGE_SIZE);
            frame_dirty[f] = 0; st.writebacks++;
        }
}

static u32 fnv(u32 h, const u8 *p, u32 n) { while (n--) { h ^= *p++; h *= 16777619u; } return h; }
static u32 store_checksum(void)
{
    u32 h = 2166136261u;
    h = fnv(h, flash_store, 8 * PAGE_SIZE);                 /* dictionary pages 0..7 */
    h = fnv(h, flash_store + 1024u * PAGE_SIZE, 16 * PAGE_SIZE);   /* data pages 1024..1039 */
    h = fnv(h, psram, 4 * PAGE_SIZE);
    return h;
}

/* ---- reset: rebuild the dictionary region and the primitive image ---- */
static void boot_init_call(void) { boot_init(); }
static void vm_protected(void (*fn)(void))
{
    for (;;) {
        if (setjmp(vm_jb) == 0) { fn(); return; }
        if (service_fault()) return;
    }
}
static void memory_reset(void)
{
    memset(flash_store, 0, FLASH_SIZE);
    memset(psram, 0, PSRAM_SIZE);
    vm_protected(boot_init_call);
}

/* GUARDRAIL: never use uforth.c's load() in this build — it calls interpret() with no fault
 * handler above it, so the first fault inside find() longjmps into a dead frame. */
static int feed_file(const char *path)
{
    char line[256];
    FILE *f = fopen(path, "r");
    if (!f) { return 1; }
    while (fgets(line, sizeof line, f)) {
        size_t n = strlen(line);
        while (n && (line[n-1] == '\n' || line[n-1] == '\r')) line[--n] = 0;
        if (n >= TIBSZ) { fclose(f); return 1; }
        feed(line);
        if (errf || st.err) { fclose(f); return 1; }
    }
    fclose(f);
    return 0;
}

/* ---- workload source (Forth lines; each line is fed to interpret()) ---- */
static const char *prelude_file = "boot_min.fs";
static const char *wl_src[] = {
    /* GUARDRAIL: no HEX/DECIMAL here — boot_min.fs defines BASE as `12 @`, which pushes the
     * variable's *contents* (10) instead of its address (12), so `16 BASE !` writes 16 into
     * V_LATEST+2 and destroys the dictionary chain. Verified on the unmodified prototype.
     * All addresses are decimal: 537395200 = 0x2008_0000 = flash page 1024. */
    "537395200 CONSTANT P1",
    "537395712 CONSTANT P2 537396224 CONSTANT P3 537396736 CONSTANT P4",
    /* P03e: PX is a 4-byte cell in flash page 1028, which this workload never touches, so +!
       on it must fault (page not resident) and the retry must re-run the dispatch.
       GUARDRAIL: do NOT make this cell *straddle* two pages (537397246 was the first choice):
       with 4 frames minus the pinned code page, the read touches page A, faults on page B, the
       retry loads B and evicts A, and the resume point is the dispatch entry — so the dispatch
       can never see both pages resident and the run dies ERR_RETRY_CAP after 302 retries
       (run-straddle.log). Two cold pages in one dispatch is a frame-capacity limit, not a
       retry/idempotency bug; the store-then-fault question needs one cold page. */
    "537397248 CONSTANT PX",
    ": BUMP   DUP @ 1+ SWAP ! ;",
    ": INIT   0 P1 ! 0 P2 ! 0 P3 ! 0 P4 ! ;",
    /* GUARDRAIL: TIBSZ is 80 and feed() rejects a longer line with "TEST BUG: line too long"
       *and* st.err=1 — which surfaces as a bogus "prelude failed" and an empty sweep. Keep every
       wl_src line under 80 chars; that is why the RMW step lives in its own word RMW. */
    ": RMW  1 PX +! ;",
    /* The one added step, reached from WORK via RMW: +! reads and writes one cell inside a
       single dispatch, so a straddling cell makes it touch two pages twice in one dispatch. */
    ": WORK P1 BUMP P2 BUMP P3 BUMP P4 BUMP RMW P1 @ P2 @ + P3 @ + P4 @ + ;",
    ": W1     20 0 DO P1 BUMP LOOP P1 @ ;",
    ": W3     10 0 DO P1 BUMP P2 BUMP P3 BUMP LOOP P1 @ P2 @ + P3 @ + ;",
    ": W12    10 0 DO I 512 * P1 + BUMP LOOP P1 @ ;",
    0
};

/* write one cell with its own retry: restoring compile state must not need a resident page
 * by luck, and it must never half-write (vm_wr32 touches all pages first) */
static int write_cell(u32 va, u32 val)
{
    u32 guard;
    for (guard = 0; guard < 64u; guard++) {
        if (setjmp(vm_jb) == 0) { vm_wr32(va, val); return 0; }
        st.retries++;
        /* GUARDRAIL: stop the moment the engine has already failed — otherwise a permanent
         * fault is retried 1000x per cell, three times per word, and the probe looks hung. */
        if (st.err) return -1;
        if (service_fault()) return -1;
    }
    st.err = PROBE_ERR_RETRY_CAP;
    printf("ERR_RETRY_CAP in write_cell addr=%u perm=%d\n", va, perm_active);
    return -1;
}

/* GUARDRAIL: interpret() itself faults (find/number/`,`), so the driver owns a restart at the
 * word boundary; without it the fault longjmps into a dead run() frame and the process dies. */
static void feed(const char *s)
{
    size_t n = strlen(s);
    u32 guard;
    if (n >= TIBSZ) { printf("TEST BUG: line too long\n"); st.err = 1; return; }
    memcpy(tib, s, n); tl = (u8)n; ti = 0;
    ip_ck.valid = 0;
    for (guard = 0; guard < RETRY_CAP; guard++) {
        if (setjmp(vm_jb) == 0) { interpret(); return; }
        st.retries++;
        if (!ip_ck.valid) { st.err = PROBE_ERR_NO_CKPT; return; }
        /* GUARDRAIL: interpret()'s retry loop had a 100000-iteration cap and ignored st.err,
         * so a permanent fault at a word boundary spun for 100005 retries and buried the
         * ERR_PAGE_FAULT_LOOP that run() had already reported. Bail out, named. */
        if (st.err) return;
        fault_w = 0; fault_ip = ip_ck.ti; fault_p = 0;
        log_fault("FAULT-INTERP", 0, ip_ck.ti, 0, vm_fault_addr, st.retries);
        ti = ip_ck.ti; sp = ip_ck.sp; rsp = ip_ck.rsp;
        memcpy(ds, ip_ck.ds, sizeof ds); memcpy(rs, ip_ck.rs, sizeof rs);
        out_truncate(ip_ck.outlen);
        if (service_fault()) return;
        if (write_cell(V_HERE, ip_ck.here)) return;
        if (write_cell(V_LATEST, ip_ck.latest)) return;
        if (write_cell(V_STATE, ip_ck.state)) return;
    }
    st.err = PROBE_ERR_RETRY_CAP;
    printf("ERR_RETRY_CAP in feed ti=%u addr=%u perm=%d\n", (unsigned)ip_ck.ti, vm_fault_addr, perm_active);
}

typedef struct { u32 sp, rsp, ds[SD], rs[SD], checksum, outhash, err, hot; } digest;

/* inject = global dispatch index whose first memory access takes a forced fault (0 = off).
 * perm   = global dispatch index whose first touched page stays permanently unusable. */
static digest run_case(int frames, const char *word, int inject, u32 perm, u32 *disp_out)
{
    digest d;
    int i;
    memset(&d, 0, sizeof d);
    /* GUARDRAIL: run_case used to set inject_at/perm_at only *after* the prelude, so a case's
     * prelude ran with the previous case's injection still armed — the first page the prelude
     * touched then became permanently unfetchable and the case "failed at 4 frames". Clear
     * both arms before vm_init, i.e. before any page is touched at all. */
    inject_at = 0; perm_at = 0; first_fault_seen = 0;
    trace_meas = 0;
    vm_init(frames);
    if (feed_file(prelude_file) || st.err) {
        printf("CASE-ERR: prelude failed at %d frames err=%s\n", frames, err_name(st.err));
        d.err = 99; return d;
    }
    for (i = 0; wl_src[i]; i++) feed(wl_src[i]);
    if (st.err) {
        printf("CASE-ERR: workload source failed at %d frames err=%s\n", frames, err_name(st.err));
        d.err = 99; return d;
    }
    /* positions are counted inside the measured workload only, not the prelude */
    st.dispatches = 0; st.no_access_positions = 0; st.peak_fpw = 0;
    faults_wake = faults_prev_wake = 0; hot_streak = 0;
    inject_at = inject; perm_at = perm; perm_active = 0; perm_arm_next = 0; perm_pg = -1;
    trace_meas = trace_on;   /* measured window only; the prelude that just ran was not traced */
    sp = rsp = 0; outlen = 0;
    feed("INIT");
    if (word) feed(word);
    if (faults_wake > st.peak_fpw) st.peak_fpw = faults_wake;
    vm_flush();
    d.sp = sp; d.rsp = rsp;
    for (i = 0; i < SD; i++) { d.ds[i] = ds[i]; d.rs[i] = rs[i]; }
    d.checksum = store_checksum();
    d.outhash = fnv(2166136261u, (const u8 *)outbuf, outlen);
    d.err = (u32)st.err; d.hot = (u32)st.hot_set;
    if (disp_out) *disp_out = st.dispatches;
    return d;
}


/* ---- costs ---- */
static double now_sec(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

static void bench_resolve(void)
{
    volatile u8 sink = 0;
    u32 va = FLASH_BASE + 1024u * PAGE_SIZE;
    double t0, t1;
    long i;
    int f;

    vm_init(MAX_FRAMES);
    if (feed_file(prelude_file)) { printf("BENCH-ERR: prelude\n"); return; }
    if (setjmp(vm_jb) == 0) sink = *resolve(va); else service_fault();

    t0 = now_sec();
    for (i = 0; i < 1000000; i++) sink = *resolve(va + (u32)(i & 63));
    t1 = now_sec();
    printf("BENCH resolve-hit-flash   : %.2f ns/call (1e6 calls, resident page)\n", (t1 - t0) * 1e9 / 1e6);

    t0 = now_sec();
    for (i = 0; i < 1000000; i++) sink = *resolve(PSRAM_BASE + (u32)(i & 63));
    t1 = now_sec();
    printf("BENCH resolve-hit-psram   : %.2f ns/call (1e6 calls)\n", (t1 - t0) * 1e9 / 1e6);

    /* one frame, alternating pages: every access is a full fault round trip */
    nframes = 1; frame_page[0] = -1; npins = 0;
    t0 = now_sec();
    for (i = 0; i < 200000; i++) {
        u32 a = FLASH_BASE + (1024u + (u32)(i & 1)) * PAGE_SIZE + 8u;
        if (setjmp(vm_jb) == 0) sink = *resolve(a); else service_fault();
    }
    t1 = now_sec();
    printf("BENCH resolve-miss+fault  : %.2f ns/fault (2e5 faults, incl. writeback+load)\n", (t1 - t0) * 1e9 / 2e5);
    (void)f; (void)sink;
}

/* ---- main ---- */
static void debug_prelude(void);

/* P03b answers one thing at one configuration: 4 frames, one workload, every dispatch
 * position. P03's frame/workload matrix belongs to P03 and is not repeated here. */
#define TEST_FRAMES    4
#define WORKLOAD       "WORK"   /* 4 pageable data pages, ~200 dispatch positions */
#define SWEEP_DEADLINE 20.0     /* internal wall-clock bound: the whole run fits `timeout 30` */
#define PERM_PROBE_MAX 8

/* GUARDRAIL: one binary, two cases, only `inject_at` different — P03c's pass criterion is "same
 * build, differing only in the injection", so the trace must not live in a second program that
 * could drift from the sweep's. */
#define SPEC_POS 61

static void trace_case(const char *tag, int inject, const char *path)
{
    digest d;
    u32 D = 0;
    tlog = fopen(path, "w");
    if (!tlog) { printf("BLOCKED: cannot open %s\n", path); return; }
    trace_on = 1;
    d = run_case(TEST_FRAMES, WORKLOAD, inject, 0, &D);
    trace_on = 0; trace_meas = 0;
    fclose(tlog); tlog = NULL;
    printf("TRACE %s inject=%d disp=%u faults=%lu retries=%lu resume_mismatch=%lu sp=%u rsp=%u ds0=%u chk=%08x out=%08x err=%s file=%s\n",
           tag, inject, D, st.faults, st.retries, st.resume_mismatch, d.sp, d.rsp, d.ds[0],
           d.checksum, d.outhash, err_name((int)d.err), path);
}

static int digest_equal(const digest *a, const digest *b)
{
    /* GUARDRAIL: compare only the *live* stack cells (indices < sp/rsp). Cells above the stack
     * pointer are dead, and a retry legitimately leaves different dead bytes there — comparing
     * all SD cells reported 105 phantom mismatches whose live stack and checksum were equal. */
    return a->sp == b->sp && a->rsp == b->rsp && a->checksum == b->checksum &&
           a->outhash == b->outhash &&
           memcmp(a->ds, b->ds, (size_t)a->sp * sizeof a->ds[0]) == 0 &&
           memcmp(a->rs, b->rs, (size_t)a->rsp * sizeof a->rs[0]) == 0;
}

int main(int argc, char **argv)
{
    unsigned k, D = 0, tested = 0, fired = 0, noaccess = 0, mismatches = 0, skipped = 0;
    unsigned long faults_total = 0, retries_total = 0, forced_evicts = 0, resume_total = 0;
    double t_start, deadline;
    int loop_ok = 0;

    psram = (u8 *)malloc(PSRAM_SIZE);
    flash_store = (u8 *)malloc(FLASH_SIZE);
    if (!psram || !flash_store) { printf("BLOCKED: cannot allocate the 1 MB fake regions\n"); return 2; }
    /* GUARDRAIL: line buffered and redirected by the shell — P03 piped a long run through
     * `head` and lost the only copy of its hang position. Never do that again. */
    setvbuf(stdout, NULL, _IOLBF, 0);
    if (argc > 1 && !strcmp(argv[1], "debug")) { debug_prelude(); return 0; }
    if (argc > 1 && !strcmp(argv[1], "bench")) { vm_init(TEST_FRAMES); bench_resolve(); return 0; }    flog = fopen("faults.log", "w");
    if (!flog) { printf("BLOCKED: cannot open faults.log\n"); return 2; }
    /* GUARDRAIL: `trace` is the whole probe and it runs the *same* run_case path as the sweep — a
     * separate tracing driver would answer a different question than P03b asked. */
    if (argc > 1 && !strcmp(argv[1], "trace")) {
        trace_case("base", 0, "trace-base.log");
        trace_case("fault", SPEC_POS, "trace-f61.log");
        fclose(flog);
        return 0;
    }

    t_start = now_sec();
    printf("# P03b retry progress: page=%d B, frames=%d, workload=%s, wake=%d dispatches\n",
           PAGE_SIZE, TEST_FRAMES, WORKLOAD, WAKE_DISPATCHES);

    /* (1) BASELINE FIRST — no injection. A broken baseline aborts the run; sweeping a broken
     * fixture is exactly what P03 did and it produced zero usable positions. */
    printf("\n## baseline\n");
    {
        digest base = run_case(TEST_FRAMES, WORKLOAD, 0, 0, &D);
        printf("baseline frames=%d disp=%u faults=%lu loads=%lu writebacks=%lu sp=%u rsp=%u ds0=%u chk=%08x out=%08x err=%s\n",
               TEST_FRAMES, D, st.faults, st.loads, st.writebacks, base.sp, base.rsp, base.ds[0],
               base.checksum, base.outhash, err_name((int)base.err));
        if (base.err != PROBE_OK) {
            printf("BLOCKED: baseline broken err=%s chk=%08x (no sweep attempted)\n",
                   err_name((int)base.err), base.checksum);
            printf("\nSUMMARY baseline_valid=no positions=%u tested=0 mismatches=not-measured loop_bound=not-measured\n", D);
            fclose(flog);
            return 3;
        }
        /* (2) PROGRESS BOUND: a permanently unusable page must produce the named error. */
        printf("\n## permanent fault (progress bound)\n");
        for (k = 1; k <= PERM_PROBE_MAX && k <= D; k++) {
            digest d = run_case(TEST_FRAMES, WORKLOAD, 0, k, 0);
            printf("perm pos=%u err=%s retries=%lu perm_faults=%lu dispatches=%lu\n",
                   k, err_name((int)d.err), st.retries, st.perm_faults, st.dispatches);
            if (d.err == PROBE_ERR_FAULT_LOOP) { loop_ok = 1; break; }
            if (d.err == PROBE_OK && st.perm_faults == 0) {
                printf("perm pos=%u not armed: dispatch touched no pageable memory\n", k);
            }
        }
        printf("loop_bound=resolved err=%s at pos=%u\n",
               loop_ok ? "ERR_PAGE_FAULT_LOOP" : "NOT-FIRED", loop_ok ? k : 0);

        /* (3) THE SWEEP: one run per dispatch position, fault injected exactly there. */
        printf("\n## idempotency sweep (frames=%d)\n", TEST_FRAMES);
        deadline = t_start + SWEEP_DEADLINE;
        for (k = 1; k <= D; k++) {
            digest d;
            if (now_sec() > deadline) {
                skipped = D - k + 1;
                printf("PARTIAL: wall-clock bound at position %u of %u\n", k, D);
                break;
            }
            d = run_case(TEST_FRAMES, WORKLOAD, (int)k, 0, 0);
            tested++;
            faults_total += st.faults; retries_total += st.retries;
            resume_total += st.resume_mismatch;   /* GUARDRAIL: st is per-case, so accumulate */
            forced_evicts += st.loads_forced_evict;
            noaccess += (u32)(st.spurious == 0);
            fired += (st.spurious > 0);
            printf("pos=%u fired=%d spurious=%lu evict=%lu faults=%lu retries=%lu err=%s disp=%lu chk=%08x out=%08x sp=%u rsp=%u first=(w=%u,ip=%u,p=%u)\n",
                   k, st.spurious > 0, st.spurious, st.loads_forced_evict, st.faults, st.retries,
                   err_name((int)d.err), st.dispatches, d.checksum, d.outhash, d.sp, d.rsp,
                   first_w, first_ip, first_p);
            if (d.err != PROBE_OK || !digest_equal(&d, &base)) {
                mismatches++;
                printf("MISMATCH pos=%u w=%u ip=%u p=%u err=%s chk=%08x/%08x out=%08x/%08x sp=%u/%u rsp=%u/%u ds0=%u/%u\n",
                       k, fault_w, fault_ip, fault_p, err_name((int)d.err),
                       d.checksum, base.checksum, d.outhash, base.outhash,
                       d.sp, base.sp, d.rsp, base.rsp, d.ds[0], base.ds[0]);
            }
        }
        printf("\nsweep: positions=%u tested=%u injected_fired=%u no_access=%u skipped=%u mismatches=%u faults=%lu retries=%lu forced_evicts=%lu resume_mismatch=%lu\n",
               D, tested, fired, noaccess, skipped, mismatches, faults_total, retries_total, forced_evicts, resume_total);
        printf("SUMMARY baseline_valid=yes frames=%d workload=%s positions=%u tested=%u mismatches=%u hangs=0 loop_bound=%s elapsed=%.1fs\n",
               TEST_FRAMES, WORKLOAD, D, tested, mismatches, loop_ok ? "ERR_PAGE_FAULT_LOOP" : "NOT-FIRED",
               now_sec() - t_start);
    }
    fclose(flog);
    return (mismatches || !loop_ok) ? 1 : 0;
}

/* debug: prelude line by line */
static void debug_prelude(void)
{
    char line[256];
    int ln = 0;
    FILE *f = fopen(prelude_file, "r");
    if (!f) return;
    vm_init(MAX_FRAMES);
    while (fgets(line, sizeof line, f) && ln < 200) {
        size_t n = strlen(line);
        while (n && (line[n-1] == '\n' || line[n-1] == '\r')) line[--n] = 0;
        ln++;
        errf = 0;
        feed(line);
        printf("%2d errf=%d err=%d HERE=%u LATEST=%u sp=%u faults=%lu retries=%lu ti=%u tl=%u | %s\n",
               ln, errf, st.err, rd32_now(V_HERE), rd32_now(V_LATEST), sp, st.faults, st.retries, ti, tl, line);
        if (errf) break;
    }
    fclose(f);
    for (ln = 0; wl_src[ln]; ln++) {
        errf = 0;
        trace_sys = 1;
        printf("WL %d START ti=%u tl=%u\n", ln, ti, tl);
        feed(wl_src[ln]);
        trace_sys = 0;
        printf("WL %d errf=%d err=%d HERE=%u LATEST=%u sp=%u faults=%lu retries=%lu | %s\n",
               ln, errf, st.err, rd32_now(V_HERE), rd32_now(V_LATEST), sp, st.faults, st.retries, wl_src[ln]);
    }
}
