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

static struct stats {
    unsigned long hits, faults, spurious, loads, writebacks, bad_addr, no_victim, hot_set;
    unsigned long dispatches, retries, resume_mismatch, no_access_positions;
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
    f = find_frame(pg);
    if (f >= 0) {
        st.hits++;
        frame_used[f] = ++lru_clock;
        if (va < DICT_WINDOW) pin_page(pg);          /* code pages of the running definition */
        return &frame_mem[f][va & (PAGE_SIZE - 1)];
    }
    if (vm_spurious_armed) {                          /* injected fault: page already resident */
        vm_spurious_armed = 0; vm_spurious_fired = 1;
        st.spurious++;
        raise_fault(va, VM_FAULT_MISS);
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

static void ckpt_save(u32 w, u32 ip, u32 p)
{
    ck.w = (u16)w; ck.ip = (u16)ip; ck.p = (u16)p;
    ck.sp = sp; ck.rsp = rsp;
    memcpy(ck.ds, ds, sizeof ds); memcpy(ck.rs, rs, sizeof rs);
    ck.outlen = outlen; ck.valid = 1;
}
void vm_ckpt_fetch(u32 w, u32 ip, u32 p)    { ckpt_save(w, ip, p); }
void vm_ckpt_dispatch(u32 w, u32 ip, u32 p) { ckpt_save(w, ip, p); }
void vm_ckpt_next(u32 w, u32 ip, u32 p)     { ckpt_save(w, ip, p); }

static u32 rd32_now(u32 a) { return vm_rd32(a); }

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
    for (;;) {
        if (setjmp(vm_jb) == 0) { (void)run_from(r_w, r_ip, r_p); memcpy(&vm_jb, &saved, sizeof vm_jb); return; }
        st.retries++;
        if (!ck.valid) { st.err = 1; memcpy(&vm_jb, &saved, sizeof vm_jb); return; }
        fault_w = ck.w; fault_ip = ck.ip; fault_p = ck.p;
        sp = ck.sp; rsp = ck.rsp;
        memcpy(ds, ck.ds, sizeof ds); memcpy(rs, ck.rs, sizeof rs);
        out_truncate(ck.outlen);
        /* the resume point must be the faulting primitive dispatch, not a token boundary */
        if (ck.w != r_w || ck.ip != r_ip) st.resume_mismatch++;
        r_w = ck.w; r_ip = ck.ip; r_p = ck.p;
        if (++guard > 4000000u) { st.err = 1; memcpy(&vm_jb, &saved, sizeof vm_jb); return; }
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
    memory_reset();
    vm_armed_from_prev = vm_spurious_fired = vm_spurious_armed = 0;
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
    ": BUMP   DUP @ 1+ SWAP ! ;",
    ": INIT   0 P1 ! 0 P2 ! 0 P3 ! 0 P4 ! ;",
    ": WORK   P1 BUMP P2 BUMP P3 BUMP P4 BUMP P1 @ P2 @ + P3 @ + P4 @ + ;",
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
    for (guard = 0; guard < 1000u; guard++) {
        if (setjmp(vm_jb) == 0) { vm_wr32(va, val); return 0; }
        st.retries++;
        if (service_fault()) return -1;
    }
    st.err = 1;
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
    for (guard = 0; guard < 100000u; guard++) {
        if (setjmp(vm_jb) == 0) { interpret(); return; }
        st.retries++;
        if (!ip_ck.valid) { st.err = 1; return; }
        fault_w = 0; fault_ip = ip_ck.ti; fault_p = 0;
        ti = ip_ck.ti; sp = ip_ck.sp; rsp = ip_ck.rsp;
        memcpy(ds, ip_ck.ds, sizeof ds); memcpy(rs, ip_ck.rs, sizeof rs);
        out_truncate(ip_ck.outlen);
        if (service_fault()) return;
        if (write_cell(V_HERE, ip_ck.here)) return;
        if (write_cell(V_LATEST, ip_ck.latest)) return;
        if (write_cell(V_STATE, ip_ck.state)) return;
    }
    st.err = 1;
}

typedef struct { u32 sp, rsp, ds[SD], checksum, outhash, err, hot; } digest;

static digest run_case(int frames, const char *word, int inject, u32 *disp_out)
{
    digest d;
    int i;
    vm_init(frames);
    if (feed_file(prelude_file) || st.err) { printf("CASE-ERR: prelude failed at %d frames\n", frames); d.err = 99; return d; }
    for (i = 0; wl_src[i]; i++) feed(wl_src[i]);
    if (st.err) { printf("CASE-ERR: workload source failed at %d frames\n", frames); d.err = 99; return d; }
    /* positions are counted inside the measured workload only, not the prelude */
    st.dispatches = 0; st.no_access_positions = 0; st.peak_fpw = 0;
    faults_wake = faults_prev_wake = 0; hot_streak = 0;
    inject_at = inject;
    sp = rsp = 0; outlen = 0;
    feed("INIT");
    if (word) feed(word);
    if (faults_wake > st.peak_fpw) st.peak_fpw = faults_wake;
    vm_flush();
    d.sp = sp; d.rsp = rsp;
    for (i = 0; i < SD; i++) d.ds[i] = ds[i];
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
static int frames_set[] = {2, 4, 8};
#define NFRAMES_SET ((int)(sizeof frames_set / sizeof frames_set[0]))

int main(int argc, char **argv)
{
    if (argc > 1 && !strcmp(argv[1], "debug")) {
        psram = (u8 *)malloc(PSRAM_SIZE); flash_store = (u8 *)malloc(FLASH_SIZE);
        debug_prelude(); return 0;
    }
    int i, k;
    u32 D = 0, tested = 0, noaccess = 0, mismatches = 0;
    double t_start = now_sec();

    psram = (u8 *)malloc(PSRAM_SIZE);
    flash_store = (u8 *)malloc(FLASH_SIZE);
    if (!psram || !flash_store) { printf("BLOCKED: cannot allocate the 1 MB fake regions\n"); return 2; }
    printf("# P03 paging sim: page=%d B, frames up to %d, server latency=%d units, wake=%d dispatches\n",
           PAGE_SIZE, MAX_FRAMES, SERVER_LATENCY, WAKE_DISPATCHES);

    /* (1) prelude compilation */
    printf("\n## prelude\n");
    for (i = 0; i < NFRAMES_SET; i++) {
        vm_init(frames_set[i]);
        if (feed_file(prelude_file)) { printf("prelude frames=%d COMPILE-FAILED faults=%lu hot=%lu err=%d\n", frames_set[i], st.faults, st.hot_set, st.err); continue; }
        if (faults_wake > st.peak_fpw) st.peak_fpw = faults_wake;
        printf("prelude frames=%d faults=%lu loads=%lu writebacks=%lu no_victim=%lu peak_fpw=%lu hot=%lu err=%d\n",
               frames_set[i], st.faults, st.loads, st.writebacks, st.no_victim, st.peak_fpw,
               st.hot_set, st.err);
    }

    /* (2) frame sweep: 2/4/8 frames x 1/3/12 page workloads */
    printf("\n## frame sweep\n");
    {
        const char *wl[] = {"W1", "W3", "W12"};
        for (i = 0; i < NFRAMES_SET; i++) {
            for (k = 0; k < 3; k++) {
                u32 disp = 0;
                digest d = run_case(frames_set[i], wl[k], 0, &disp);
                printf("%s frames=%d faults=%lu spurious=%lu loads=%lu writebacks=%lu no_victim=%lu peak_fpw=%lu hot=%lu err=%d disp=%u chk=%08x\n",
                       wl[k], frames_set[i], st.faults, st.spurious, st.loads, st.writebacks,
                       st.no_victim, st.peak_fpw, st.hot_set, d.err, disp, d.checksum);
            }
        }
    }

    /* (3) exhaustive idempotency sweep over the 4-page workload */
    printf("\n## idempotency sweep\n");
    {
        digest base = run_case(MAX_FRAMES, "WORK", 0, &D);
        u32 base_faults = (u32)st.faults;
        printf("baseline frames=%d disp=%u faults=%lu sp=%u rsp=%u chk=%08x out=%08x err=%u\n",
               MAX_FRAMES, D, st.faults, base.sp, base.rsp, base.checksum, base.outhash, base.err);
        if (base.err) { printf("BASELINE-ERR: aborting sweep\n"); }
        else {
            for (k = 1; k <= (int)D; k++) {
                digest d;
                if (now_sec() - t_start > 1200.0) { printf("PARTIAL: wall clock at position %d of %u\n", k, D); break; }
                d = run_case(MAX_FRAMES, "WORK", k, 0);
                tested++;
                noaccess += (u32)st.no_access_positions;
                if (d.err || d.sp != base.sp || d.rsp != base.rsp ||
                    d.checksum != base.checksum || d.outhash != base.outhash ||
                    memcmp(d.ds, base.ds, sizeof base.ds) != 0) {
                    mismatches++;
                    printf("MISMATCH at position %u: w=%u ip=%u p=%u sp=%u/%u chk=%08x/%08x err=%u ds0=%u\n",
                           (u32)k, fault_w, fault_ip, fault_p, d.sp, base.sp, d.checksum, base.checksum, d.err, d.ds[0]);
                }
            }
            printf("sweep: positions=%u tested=%u mismatches=%u no_access_positions=%u baseline_faults=%u\n",
                   D, tested, mismatches, noaccess, base_faults);
        }
    }

    /* (4) resolve cost */
    printf("\n## costs\n");
    bench_resolve();
    printf("elapsed=%.1fs\n", now_sec() - t_start);
    return mismatches ? 1 : 0;
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
