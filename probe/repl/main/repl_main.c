/* repl_main.c — the HP side: a dumb byte pump between UART0 and the ULP's two rings.
 *
 * It does not parse Forth, does not queue commands, and does not decide anything. That is the whole
 * point of the split: the interpreter is on the ULP, this core moves bytes and nothing else (R6).
 *
 * You talk to it with any terminal:  picocom -b 115200 /dev/ttyACM1
 *
 * GUARDRAIL: the ULP is armed only after the banner is printed and the port is up. A board that is
 * armed before it can talk is a board that wedges silently — the P06 lesson, which cost a physical
 * reset and the firmware that was on the chip.
 *
 * GUARDRAIL: one writer per ring index. This task writes cmd_head and out_tail; the ULP writes
 * cmd_tail and out_head. Both are u32-aligned, so no lock is needed for the counters, and adding one
 * would be the only place a deadlock could live.
 */
#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "soc/soc.h"
/* The ULP writes ONE byte per message into repl_out[] (0x81..) and msg_expand.h turns it back into text
 * here. Every other byte in that ring is ASCII (echoed input, digits, the offending word, '?', '\n'), so a
 * byte >= 0x80 is unambiguously a code, and the expansion is a substitution at the same position in the
 * stream: the transcript keeps its bytes and its order against the echo.
 * GUARDRAIL: a relative include, not an include dir. main/CMakeLists.txt deliberately keeps
 * COMPONENT_ADD_INCLUDEDIRS empty so the ULP can never pick up a different uforth.c; adding src/ to the
 * host's search path to reach one header would undo that. One list, both cores (R6). */
#include "../src/msg_expand.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "ulp_riscv.h"
#include "ulp_main.h"

static void seed_poll(void);   /* defined after blkfile[]; called from the UART pump */

#define CONSOLE_UART  UART_NUM_0
#define CONSOLE_BAUD  115200

static const char *TAG = "repl";

/* The generated header declares these as uint32_t; the ring members are bytes inside them, so the
 * address is what matters. Same trick P22 proved with mem[]. */
#define CMD_BYTES  ((volatile uint8_t *)&ulp_repl_cmd)
#define OUT_BYTES  ((volatile uint8_t *)&ulp_repl_out)
/* GUARDRAIL: must equal the ULP's CMD_SIZE/OUT_SIZE. They lived in two files with no link between
 * them; when the ULP rings shrank to 64/128 and this stayed at 128/256, the host wrote past the end of
 * repl_cmd[] into repl_out[] and the REPL replayed old characters. The boot assert below is the link. */
#define CMD_SIZE   64u
#define OUT_SIZE   128u
#define CMD_MASK   (CMD_SIZE - 1u)
#define OUT_MASK   (OUT_SIZE - 1u)

extern const uint8_t bin_start[] asm("_binary_ulp_main_bin_start");
extern const uint8_t bin_end[]   asm("_binary_ulp_main_bin_end");

/* ---- R5: the block byte server -------------------------------------------------
 * The ULP cannot reach flash or PSRAM: it sees only its own 256 B window in RTC RAM. This task is the
 * other end of the protocol — it polls one flag, copies bytes, checksums, and writes the status LAST so
 * the ULP can never read a half-copied buffer. Backend today is an 8 x 256 B RAM array; flash (R7) plugs
 * in here without touching the protocol, which is the whole point of keeping the coprocessor dumb.
 * GUARDRAIL: the ULP links at address 0, so the addresses it publishes are OFFSETS into RTC slow memory.
 * Dereferencing one directly panics: LoadProhibited, EXCVADDR = the mailbox offset (E-073).
 * GUARDRAIL: created BEFORE the console pump: a higher-priority task that never yields can starve app_main,
 * and then anything created after it silently never exists. */
#define ULP_RAM_BASE ((uint32_t)SOC_RTC_DATA_LOW)

static void console_task(void *arg)
{
    (void)arg;
    uint8_t buf[64];

    for (;;) {
        /* GUARDRAIL: read AT MOST what the ring can hold, and never read more than that into `buf`.
         * The old form read up to 64 bytes and then `break`ed when the ring filled — but those bytes had
         * already been taken out of the UART FIFO, so everything after the break was SILENTLY LOST. The
         * comment claimed "drop nothing"; the code dropped the tail of every burst longer than the free
         * space. Measured on the device: an 88-character definition arrived mangled (`ARITH?`, then `DUP?`)
         * and the benchmark lines — the longest being 88 chars — could not be typed at all.
         * Sizing the read to the free space makes the ring the only limit, which is what the ring is for. */
        /* the UART is read by seed_poll(), which forwards non-seed lines into the ring */
        seed_poll();   /* fast block seeding, host-side (see seed_poll) */

        /* out ring -> UART */
        uint32_t oh = ulp_repl_out_head;
        uint32_t ot = ulp_repl_out_tail;
        if (oh != ot) {
            /* GUARDRAIL: the expansion AND the ring bookkeeping live in msg_drain_ring() so the host test
             * drives the same code, including the "does not fit" path: a message dropped instead of retried
             * looks exactly like a healthy line with no reply, and that path only fires when the staging
             * buffer is nearly full. */
            char out[MSG_OUT_TEXT];
            uint32_t n = msg_drain_ring(OUT_BYTES, OUT_MASK, oh, &ot, out, sizeof out);
            ulp_repl_out_tail = ot;
            if (n) uart_write_bytes(CONSOLE_UART, out, n);
        }

        vTaskDelay(1);
    }
}

/* GUARDRAIL: the server body is the one the experimental tree verified on hardware (E-074); it is
 * 2048 B of stack on the HP and never touches the ULP's pool. */
/* GUARDRAIL: 8 -> 128 blocks (16 KB at the ULP's 128 B transfer size). Eight blocks is 1 024 B of source,
 * about 600-800 B of compiled code, which is LESS than the 1 183 B of resident app space the overlay build
 * has - so overlays could not raise the program ceiling at all while the store was 8 blocks. Measured on the
 * board: blocks 0..7 answered and 8+ nacked. The host has megabytes; the ULP's RAM is the scarce side, so
 * the store is the cheap place to buy capacity. 128 x 256 B = 32 KB of host RAM. */
#define BLK_N     128
#define BLK_SZ    256
static uint32_t blk_sz;      /* transfer size, published by the ULP */
/* GUARDRAIL: test-only stall for the op-3 race test. `#s <ms>` makes this task sleep once, so the ULP times out on its
 * next block request. Main-core only, zero ULP bytes; without it the race cannot be provoked deliberately. */
static uint32_t stall_ms;
static int blk_out_prev;      /* edge detector for the ULP's outstanding-request flag */
/* GUARDRAIL: when this task first SAW the request. The ULP's wait (BLKWAIT 2 000 000 iterations) is ~845 ms MEASURED
 * on hardware, and on a timeout the ULP deliberately leaves blk_out set - so the flag alone cannot distinguish "still
 * waiting" from "gave up". A destructive op (image load) must therefore be applied only inside a conservative fraction
 * of that window; outside it, refuse loudly instead of adopting a dictionary the machine was told it does not have.
 * Failure mode is a named nack, never silent corruption. */
static uint32_t edge_ms;
static uint8_t blkfile[BLK_N][BLK_SZ];   /* the ARRAY is sized for the max; blk_sz is the transfer size */
/* ---- ULP stack high-water probe (row 10 of the A/B) ---------------------------------------------------------
 * The ULP stack grows down from ulp___stack_top (0x50001ff0) into .bss, so an overflow corrupts engine state
 * instead of faulting - that is how a 336 B chain silently broke block I/O earlier. The main core can WRITE RTC
 * slow RAM, so it paints the region above the image with 0xA5 before the ULP starts, and afterwards reports the
 * lowest byte the ULP has touched. That turns the frame arithmetic into a measurement at zero cost in ULP bytes.
 *
 * GUARDRAIL: the paint starts at 0x1EB0, not at pool_end. The pool ends at 0x1EA7 with this image (7847 B) and
 * painting from below that would erase mem[]/tib/mailbox - a "measurement" that destroys the thing it measures.
 * If the image grows past 0x1EB0 this must move down with it, which is why the end is asserted at boot.
 */
/* GUARDRAIL: the base is READ OFF THE MAP, not guessed. `riscv32-esp-elf-nm -n ulp_main.elf` puts the highest
 * .bss symbol at `junk` 0x1EA8, so the image ends at 0x1EA9 and the stack occupies [0x1EA9, 0x1FF0) = 327 B.
 * The first attempt used 0x1EB0 from the pool arithmetic and reported 1 byte, which is impossible for a machine
 * that enters vm_enter per token - the paint must be verified against this base before any number is believed.
 * GUARDRAIL: leave the injected report OFF for shipping images (comment out CANARY below): it puts a stray
 * "<n> ." line on the operator's console four seconds after boot.
 * GUARDRAIL: never write a nested comment terminator inside this comment. Writing the flag as a quoted C comment
 * here ended the enclosing block early, so the two functions below became comment text and the call in app_main
 * failed with "implicit declaration" - which reads like a missing prototype, not a comment bug. */
/* GUARDRAIL: OFF. Enabling it corrupts the console: injecting a line into the command ring made the ULP emit
 * binary noise (0x78/0x00 bytes) instead of text, so the report destroyed the very channel it used. The ring is
 * single-writer per index and the UART pump owns cmd_head in the same task, which is the likely collision - but
 * the fix is not a patch here: publish the number into an RTC cell and let a FORTH word read it, so the report
 * travels through the interpreter instead of being spliced into its input.
 * GUARDRAIL: the base IS settled: nm -n on ulp_main.elf puts the highest .bss symbol at `junk` 0x1EA8, so the
 * image ends at 0x1EA9 and the stack occupies [0x1EA9, 0x1FF0) = 327 B. 0x1EAC is the map's answer, not the
 * pool arithmetic that guessed 0x1EB0. */
/* #define CANARY 1 */
#define CANARY_BASE 0x1EACu
#define STACK_TOP   0x1FF0u
#define CANARY_VAL  0xA5u

static void canary_paint(void)
{
    volatile uint8_t *p = (volatile uint8_t *)(ULP_RAM_BASE + CANARY_BASE);
    uint32_t i;
    for (i = 0; i < STACK_TOP - CANARY_BASE; i++) p[i] = CANARY_VAL;
}

static uint32_t canary_used(void)
{
    volatile uint8_t *p = (volatile uint8_t *)(ULP_RAM_BASE + CANARY_BASE);
    uint32_t i, low = STACK_TOP - CANARY_BASE;
    for (i = 0; i < STACK_TOP - CANARY_BASE; i++) if (p[i] != CANARY_VAL) low = i;
    /* the stack grows DOWN from STACK_TOP, so the deepest touch is the LOWEST painted byte that changed */
    return (low < STACK_TOP - CANARY_BASE) ? (STACK_TOP - CANARY_BASE - low) : 0u;
}

/* GUARDRAIL: this lives AFTER blkfile[] and BLK_N because it writes them; the first placement sat above the
 * store's declaration and failed with "'BLK_N' undeclared", which reads like a missing include.
 * Line format:  #b <block> <hex bytes>   - intercepted here, never forwarded to the ULP. */
static void seed_poll(void)
{
    /* GUARDRAIL: 320 bytes, not 180. A full 128-byte block arrives as ~264 hex characters plus the "#b N " prefix,
     * so a 180-byte line buffer silently seeded 87 of 128 bytes per block and the phase source could not assemble
     * (measured as IDX? / Z1? during the load, and as a readback of 87 bytes). Size for the worst case. */
    static char ln[320];
    static int n;
    unsigned char c;
    while (uart_read_bytes(CONSOLE_UART, &c, 1, 0) == 1) {
        if (c == '\n' || c == '\r') {
            ln[n] = 0;
            if (n > 4 && ln[0] == '#' && ln[1] == 'b' && ln[2] == ' ') {
                unsigned blk = 0, k = 3, w = 0;
                int hi = 0, bad = 0;
                while (ln[k] >= '0' && ln[k] <= '9') blk = blk * 10u + (unsigned)(ln[k++] - '0');
                while (ln[k] == ' ') k++;
                /* GUARDRAIL: blank the block BEFORE writing the payload. Writing only the payload leaves the rest
                 * of the block holding whatever a previous seed put there; LOAD then compiles the new text and
                 * trips over the stale tail, which errors the line and REWINDS the phase - measured as a phase
                 * whose own definitions vanished (Z6?, and a minimal `: ZZ 42 . ;` in one block + `ZZ` in the
                 * next answering ZZ?). */
                if (blk < BLK_N) {
                    unsigned i2;
                    for (i2 = 0; i2 < sizeof(blkfile[0]); i2++) blkfile[blk][i2] = (uint8_t)' ';
                }
                while (ln[k] && w < (unsigned)sizeof(blkfile[0]) * 2u) {
                    int v;
                    char d = ln[k];
                    if (d >= '0' && d <= '9') v = d - '0';
                    else if (d >= 'a' && d <= 'f') v = d - 'a' + 10;
                    else if (d >= 'A' && d <= 'F') v = d - 'A' + 10;
                    else { bad = 1; break; }
                    if ((w & 1u) == 0u) hi = v;
                    else if (blk < BLK_N) blkfile[blk][w >> 1] = (uint8_t)((hi << 4) | v);
                    w++; k++;
                }
                if (!bad && blk < BLK_N) printf("seed: block %u <- %u bytes\n", blk, w / 2u);
                else                     printf("seed: REJECTED (bad hex, or block >= %d)\n", BLK_N);
                fflush(stdout);
                n = 0;
                continue;                       /* a seed line is consumed here, never forwarded */
            }
            /* GUARDRAIL: `#d` builds an IMAGE of the loaded phase on the MAIN CORE, at zero ULP bytes. A Forth dumper
             * cannot do it: given the same 690 B window it needs ~370 B for the copy loop plus the 516 B phase, measured
             * as ERR_DICT. The main core already reads the ULP's mem[] (ULP_RAM_BASE + ulp_repl_mem_addr) and owns the
             * block store, so it is the right place for this - no parsing, no window, no resident cost.
             * Format:  #d <desc_blk> <code_start> <code_end> <hdr_start> <hdr_end>
             * The four addresses come from the machine: `bh @ . bl @ . HERE . LATEST .` after SEAL.
             * Descriptor v2 (20 B then the payload): FI(2) ver(1) code_len(2) hdr_len(2) code_start(2)
             * hdr_start(2) payload_sum(2) resident_sum(2) entry_xt(2) reserved(3).
             * GUARDRAIL: the ENTRY XT is part of the descriptor because a binary load cannot run what the phase's
             * top-level text ran (hook assignment, PUMP, initial stores). The caller receives the xt and EXECUTEs it;
             * the phase itself must define things and nothing else. */
            if (n > 4 && ln[0] == '#' && ln[1] == 'd' && ln[2] == ' ') {
                unsigned v[6] = {0}; int k = 3, vi = 0, bad2 = 0;
                while (vi < 6) {
                    while (ln[k] == ' ') k++;
                    if (!ln[k] || ln[k] < '0' || ln[k] > '9') { bad2 = 1; break; }
                    while (ln[k] >= '0' && ln[k] <= '9') v[vi] = v[vi] * 10u + (unsigned)(ln[k++] - '0');
                    vi++;
                }
                if (bad2 || vi < 6) {
                    printf("dump: REJECTED (want: #d <blk> <cs> <ce> <hs> <he> <entry_xt>)\n");
                } else if (v[0] + 1u >= BLK_N || v[2] < v[1] || v[4] <= v[3]
                           || 20u + (v[2] - v[1]) + (v[4] - v[3]) > (BLK_N - v[0]) * 128u) {
                    printf("dump: REJECTED (range or block overflow)\n");
                } else {
                    const uint8_t *memimg = (const uint8_t *)(ULP_RAM_BASE + ulp_repl_mem_addr);
                    /* GUARDRAIL: the descriptor SHARES the first payload block (12 B of its 128), it does not get a
                     * block of its own. Measured: 576 B of payload is 5 blocks, and reserving a block for the
                     * descriptor made it 6 - which is the difference between passing the <=65% gate and failing it. */
                    unsigned i2, payload = 0, sum = 0, blk = v[0], off = 20;
                    for (i2 = 0; i2 < BLK_SZ; i2++) blkfile[v[0]][i2] = (uint8_t)' ';
                    /* GUARDRAIL: flush on the TRANSFER size (blk_sz, published by the ULP = 128), never on BLK_SZ.
                     * BLK_SZ is only the array's row WIDTH (256). Flushing at 256 packed two blocks into one row, so the
                     * ULP read the first 128 bytes and everything after was invisible - measured as image byte 0
                     * matching while bytes at 127, 300 and 500 did not.
                     * GUARDRAIL: this macro must stay on ONE line. Splitting it to add the comment above broke the
                     * backslash continuation, the body became real code, and the build failed with 'by_' undeclared. */
#define DUMP_EMIT(byte) do { uint8_t by_ = (uint8_t)(byte); sum = (sum + by_) & 0xffffu; blkfile[blk][off++] = by_; if (off == (blk_sz ? blk_sz : 128u)) { off = 0; blk++; } payload++; } while (0)
                    for (i2 = v[1]; i2 < v[2]; i2++) DUMP_EMIT(memimg[i2]);   /* code */
                    for (i2 = v[3]; i2 < v[4]; i2++) DUMP_EMIT(memimg[i2]);   /* headers */
#undef DUMP_EMIT
                    {
                        uint8_t *d2 = blkfile[v[0]];
                        unsigned cl = v[2] - v[1], hl = v[4] - v[3];
                        d2[0] = 'F'; d2[1] = 'I'; d2[2] = 1;
                        d2[3] = (uint8_t)cl;  d2[4] = (uint8_t)(cl >> 8);
                        d2[5] = (uint8_t)hl;  d2[6] = (uint8_t)(hl >> 8);
                        d2[7] = (uint8_t)v[1]; d2[8] = (uint8_t)(v[1] >> 8);
                        d2[9] = (uint8_t)v[3]; d2[10] = (uint8_t)(v[3] >> 8);
                        /* 16 bytes: FI(2) ver(1) code_len(2) hdr_len(2) code_start(2) hdr_start(2)
                         * payload_sum(2) resident_sum(2) reserved(1). GUARDRAIL: the RESIDENT sum is a separate
                         * field on purpose - the payload sum only proves the image arrived intact, it says nothing
                         * about the dictionary it will be pasted onto. Editing a resident word's body without
                         * changing its length leaves HERE and LATEST identical, so pointers alone cannot detect it. */
                        d2[11] = (uint8_t)sum; d2[12] = (uint8_t)(sum >> 8);
                        /* GUARDRAIL: the entry xt must be written AFTER every other descriptor field. The 16-byte
                         * layout's old `d2[15] = 0` ("reserved") still ran after this line and zeroed the LOW byte:
                         * measured as an image whose header said RUNPH1=1282 while the descriptor handed back 1280,
                         * so the caller EXECUTEd the wrong address (cells stayed 0). Reserved bytes are not free real
                         * estate - check the field map before reusing one. */
                        d2[15] = (uint8_t)v[5]; d2[16] = (uint8_t)(v[5] >> 8);   /* entry xt, 0 = none */
                        d2[2] = 2;                                              /* descriptor version 2 */
                        {
                            unsigned rs = 0, k2;
                            for (k2 = 52u; k2 < v[1]; k2++) rs = (rs + memimg[k2]) & 0xffffu;      /* resident code */
                            /* GUARDRAIL: v[4] is the SEALED LATEST - the base of the RESIDENT headers. v[3] is the
                             * post-load LATEST, i.e. the image's OWN header base. Using v[3] folded the image into its
                             * own resident checksum, and at load time the loader compared image headers against
                             * themselves: a clean image was refused with a name collision whose two entries were
                             * byte-identical (measured with the offsets printed). */
                            for (k2 = v[4]; k2 < (unsigned)ulp_repl_blk_off; k2++) rs = (rs + memimg[k2]) & 0xffffu;
                            d2[13] = (uint8_t)rs; d2[14] = (uint8_t)(rs >> 8);
                        }
                    }
                    printf("dump: code %u + hdr %u = %u B, descriptor packed -> %u blocks from block %u, sum %u\n",
                           (unsigned)(v[2] - v[1]), (unsigned)(v[4] - v[3]), payload,
                           (20u + payload + 127u) / 128u, v[0], sum);
                }
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#s <ms>` stalls the block task ONCE. Test-only (main core, zero ULP bytes) and the only way
             * to provoke the op-3 race deliberately: without it the host answers within one FreeRTOS tick and the ULP
             * never times out, so "the host does not apply a stale request" could not be demonstrated. */
            if (n > 3 && ln[0] == '#' && ln[1] == 's' && ln[2] == ' ') {
                unsigned ms = 0; int k = 3;
                while (ln[k] == ' ') k++;
                while (ln[k] >= '0' && ln[k] <= '9') ms = ms * 10u + (unsigned)(ln[k++] - '0');
                stall_ms = ms;
                printf("stall: block task will sleep %u ms on its next request\n", ms);
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#p <blk> <off> <val>` pokes ONE byte in the store, so the loader's refusals can be exercised
             * on real data instead of argued about. Test-only, main-core only, zero ULP bytes: without it there is no
             * way to corrupt an image or forge a header hash from the console, and a refusal that has never fired is
             * not evidence. */
            if (n > 3 && ln[0] == '#' && ln[1] == 'p' && ln[2] == ' ') {
                unsigned v3[3] = {0}; int k = 3, vi = 0, bad3 = 0;
                while (vi < 3) {
                    while (ln[k] == ' ') k++;
                    if (!ln[k] || ln[k] < '0' || ln[k] > '9') { bad3 = 1; break; }
                    while (ln[k] >= '0' && ln[k] <= '9') v3[vi] = v3[vi] * 10u + (unsigned)(ln[k++] - '0');
                    vi++;
                }
                if (bad3 || vi < 3 || v3[0] >= BLK_N || v3[1] >= (blk_sz ? blk_sz : 128u) || v3[2] > 255u)
                    printf("poke: REJECTED (want: #p <blk> <off> <val>)\n");
                else {
                    blkfile[v3[0]][v3[1]] = (uint8_t)v3[2];
                    printf("poke: block %u off %u = %u\n", v3[0], v3[1], v3[2]);
                }
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#l` is RETIRED. It wrote mem[] from a console command while the REPL was running: it passed
             * only because the ULP had nothing to execute at that instant, i.e. passing by timing, which this project
             * does not accept. A binary load now happens on mailbox op 3 (see block_task): the ULP issues the request
             * and blocks inside blk_xfer, so the main core copies while the ULP is provably quiescent. */
            if (n > 3 && ln[0] == '#' && ln[1] == 'l' && ln[2] == ' ') {
                printf("load: REFUSED #l is retired - use `<desc_blk> 3 BLKXFER` from the ULP, then read the entry "
                       "xt at the block window and EXECUTE it\n");
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#p <blk> <off> <val>` pokes ONE byte in the store, so the loader's refusals can be exercised
             * on real data instead of argued about. Test-only, main-core only, zero ULP bytes: without it there is no
             * way to corrupt an image or forge a header hash from the console, and a refusal that has never fired is
             * not evidence. */
            if (n > 3 && ln[0] == '#' && ln[1] == 'p' && ln[2] == ' ') {
                unsigned v3[3] = {0}; int k = 3, vi = 0, bad3 = 0;
                while (vi < 3) {
                    while (ln[k] == ' ') k++;
                    if (!ln[k] || ln[k] < '0' || ln[k] > '9') { bad3 = 1; break; }
                    while (ln[k] >= '0' && ln[k] <= '9') v3[vi] = v3[vi] * 10u + (unsigned)(ln[k++] - '0');
                    vi++;
                }
                if (bad3 || vi < 3 || v3[0] >= BLK_N || v3[1] >= (blk_sz ? blk_sz : 128u) || v3[2] > 255u)
                    printf("poke: REJECTED (want: #p <blk> <off> <val>)\n");
                else {
                    blkfile[v3[0]][v3[1]] = (uint8_t)v3[2];
                    printf("poke: block %u off %u = %u\n", v3[0], v3[1], v3[2]);
                }
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#l <desc_blk>` ADOPTS a packed image, on the main core, at zero ULP bytes - it writes the
             * ULP's mem[] directly (the main core already reads it) and then sets V_HERE/V_LATEST, which is the same
             * rewind the machine already trusts. Four refusals, each named, because a binary load that "mostly works"
             * is the worst failure class here: the code carries absolute addresses, so a wrong base does not fail
             * fast, it executes garbage.
             *   1 FI/version      - descriptor sanity
             *   2 resident sum    - the dictionary the image was built against must be unchanged
             *   3 payload sum     - the image bytes in the store must be intact
             *   4 header hashes   - a pasted header must not shadow a resident name
             * Format: #l <desc_blk> */
            if (n > 3 && ln[0] == '#' && ln[1] == 'l' && ln[2] == ' ') {
                unsigned dblk = 0; int k = 3;
                while (ln[k] == ' ') k++;
                while (ln[k] >= '0' && ln[k] <= '9') dblk = dblk * 10u + (unsigned)(ln[k++] - '0');
                {
                    const uint8_t *desc = blkfile[dblk];
                    uint8_t *memimg = (uint8_t *)(ULP_RAM_BASE + ulp_repl_mem_addr);
                    unsigned cl = (unsigned)desc[3] | ((unsigned)desc[4] << 8);
                    unsigned hl = (unsigned)desc[5] | ((unsigned)desc[6] << 8);
                    unsigned cs = (unsigned)desc[7] | ((unsigned)desc[8] << 8);
                    unsigned hs = (unsigned)desc[9] | ((unsigned)desc[10] << 8);
                    unsigned psum = (unsigned)desc[11] | ((unsigned)desc[12] << 8);
                    unsigned rsum = (unsigned)desc[13] | ((unsigned)desc[14] << 8);
                    unsigned hdrtop = (unsigned)ulp_repl_blk_off;
                    int badl = 0;
                    if (dblk >= BLK_N || desc[0] != 'F' || desc[1] != 'I' || desc[2] != 1) {
                        printf("load: REFUSED bad descriptor (magic/version/block)\n"); badl = 1;
                    }
                    if (!badl && (cs < 52u || hs <= cs || hs > hdrtop || hdrtop - hs < hl)) {
                        printf("load: REFUSED impossible geometry (code %u hdr %u top %u)\n", cs, hs, hdrtop);
                        badl = 1;
                    }
                    if (!badl) {
                        unsigned rs = 0, k2, sum2 = 0;
                        for (k2 = 52u; k2 < cs; k2++) rs = (rs + memimg[k2]) & 0xffffu;
                        for (k2 = hs + hl; k2 < hdrtop; k2++) rs = (rs + memimg[k2]) & 0xffffu;   /* sealed LATEST */
                        if (rs != rsum) {
                            printf("load: REFUSED resident dictionary changed (sum %u, image built on %u)\n", rs, rsum);
                            badl = 1;
                        }
                    }
                    if (!badl) {
                        /* the payload lives from descriptor block, offset 16, and is a plain concatenation */
                        unsigned blk2 = dblk, off2 = 16, k2, sum2 = 0;
                        for (k2 = 0; k2 < cl + hl; k2++) {
                            sum2 = (sum2 + blkfile[blk2][off2]) & 0xffffu;
                            if (++off2 == (blk_sz ? blk_sz : 128u)) { off2 = 0; blk2++; }
                        }
                        if (blk2 >= BLK_N || sum2 != psum) {
                            printf("load: REFUSED image corrupt (sum %u, descriptor %u)\n", sum2, psum);
                            badl = 1;
                        }
                    }
                    if (!badl) {
                        /* refusal 4: any image header hash equal to a resident one would shadow a resident name */
                        unsigned blk2 = dblk, off2 = 16 + cl, k2, j, hb[3], collision = 0;
                        while (off2 >= (blk_sz ? blk_sz : 128u)) { off2 -= (blk_sz ? blk_sz : 128u); blk2++; }
                        for (k2 = 0; k2 + 2 < hl; k2 += 3) {
                            for (j = 0; j < 3; j++) {
                                unsigned p2 = off2 + j;
                                hb[j] = blkfile[blk2 + p2 / (blk_sz ? blk_sz : 128u)][p2 % (blk_sz ? blk_sz : 128u)];
                            }
                            {
                                unsigned ih = ((unsigned)hb[2] << 4) | ((unsigned)hb[1] >> 4), k3;
                                for (k3 = hs + hl; k3 + 2 < hdrtop; k3 += 3) {   /* resident base = sealed LATEST */
                                    unsigned rh = ((unsigned)memimg[k3 + 2] << 4) | ((unsigned)memimg[k3 + 1] >> 4);
                                    if (rh == ih) {
                                        /* GUARDRAIL: name the offsets. A bare hash told us a refusal fired but not
                                         * whether it was a real collision, a misaligned image entry, or a wrong stride
                                         * in the resident scan - three different bugs with the same message. */
                                        if (!collision) {
                                            printf("load: image entry @payload %u (bytes %u %u %u) hash %u == resident @%u "
                                                   "(bytes %u %u %u)\n", k2, hb[0], hb[1], hb[2], ih, k3,
                                                   memimg[k3], memimg[k3+1], memimg[k3+2]);
                                        }
                                        collision = ih;
                                    }
                                }
                            }
                            off2 += 3;
                            while (off2 >= (blk_sz ? blk_sz : 128u)) { off2 -= (blk_sz ? blk_sz : 128u); blk2++; }
                        }
                        if (collision) {
                            printf("load: REFUSED name collision, image header hash %u shadows a resident word\n",
                                   collision);
                            badl = 1;
                        }
                    }
                    if (!badl) {
                        unsigned blk2 = dblk, off2 = 16, k2;
                        for (k2 = 0; k2 < cl + hl; k2++) {          /* code first, then headers, exactly as dumped */
                            memimg[cs + k2] = blkfile[blk2][off2];
                            if (++off2 == (blk_sz ? blk_sz : 128u)) { off2 = 0; blk2++; }
                        }
                        /* GUARDRAIL: the sysvar offsets are duplicated HERE because the main core does not include
                         * src/uforth.c (it would drag the whole engine in). They must match the enum in uforth.c:
                         * V_STATE 0, V_HERE 4, V_LATEST 8, V_SEAL 12, V_LOADB 16, PAD 20, DICT 52. A drift here
                         * would write the pointers into the wrong cells and the machine would execute garbage. */
#define HP_V_HERE   4u
#define HP_V_LATEST 8u
                        memimg[HP_V_HERE] = (uint8_t)((cs + cl) & 0xffu);   /* little-endian, sysvars are u32 */
                        memimg[HP_V_HERE + 1] = (uint8_t)(((cs + cl) >> 8) & 0xffu);
                        memimg[HP_V_HERE + 2] = 0; memimg[HP_V_HERE + 3] = 0;
                        memimg[HP_V_LATEST] = (uint8_t)(hs & 0xffu);
                        memimg[HP_V_LATEST + 1] = (uint8_t)((hs >> 8) & 0xffu);
                        memimg[HP_V_LATEST + 2] = 0; memimg[HP_V_LATEST + 3] = 0;
                        printf("load: adopted code %u + hdr %u from block %u (HERE %u, LATEST %u)\n",
                               cl, hl, dblk, cs + cl, hs);
                    }
                }
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: everything that is NOT a seed line is forwarded into the ULP's command ring from HERE.
             * The pump used to read the UART as well, and two readers on one port steal each other's bytes:
             * measured as a mangled command (`LOAD?` where a LOAD was intended) and blocks that never arrived. */
            {
                uint32_t h = ulp_repl_cmd_head, tl = ulp_repl_cmd_tail, space = CMD_SIZE - (h - tl);
                uint32_t i;
                /* GUARDRAIL: a line longer than the ring was forwarded PARTIALLY - `for (... && i < space ...)` cut it
                 * and the ULP then executed a truncated command. Measured: a 71-char definition echoed as
                 * `... 1 + REPEAT DRO` and compiled a definition that never closed, with NO error anywhere; the next
                 * lines were then compiled into it instead of being interpreted. The interactive limit is CMD_SIZE-1
                 * = 63 bytes (the seeder's `#b` path has its own 320-byte buffer and is unaffected). Refuse the whole
                 * line by name: a partial command must never reach the machine. */
                if ((uint32_t)n + 1u > space || (uint32_t)n + 1u > CMD_SIZE) {
                    printf("line too long: %d bytes, the ring holds %u - NOT sent\r\n", n, (unsigned)(CMD_SIZE - 1u));
                    fflush(stdout);
                    n = 0;
                    continue;
                }
                ln[n] = '\r';
                for (i = 0; i <= (uint32_t)n; i++) CMD_BYTES[(h + i) & CMD_MASK] = (uint8_t)ln[i];
                ulp_repl_cmd_head = h + i;
            }
            n = 0;
        } else if (n < (int)sizeof(ln) - 1) {
            ln[n++] = (char)c;
        }
    }
}

static void block_task(void *arg)
{
    (void)arg;
    /* GUARDRAIL: the first board run answered ERR_NO_SERVER on the ULP side while this task looked
     * healthy, so the server now reports what it can actually see: the published addresses once, and a
     * count of requests. Without this the only symptom is a timeout on the other core. */
    /* GUARDRAIL: this diagnostics block interleaves with the operator's own echo and turns a clean
     * transcript into noise. Keep it behind a flag, OFF by default: the console is the product. */
    /* GUARDRAIL: this initialisation must NOT be inside a debug guard. It spent one build inside
     * `#if defined(BLK_DEBUG)`, so with debug off `blk_sz` stayed 0, every copy loop did nothing, and the
     * only symptom was SAVE reporting +4 (a nacked checksum over zero bytes) while the data never moved.
     * A variable that decides correctness is not a diagnostic.
     * GUARDRAIL: the size comes from the ULP, never from a local constant: two `#define BLK_SZ` values that
     * disagree make every SAVE nack with a plausible code and overrun mem[] on the way. Refuse to serve
     * rather than serve wrongly. */
    blk_sz = (uint32_t)ulp_repl_blk_sz;
    if (blk_sz == 0u || blk_sz > BLK_SZ) {
        printf("FATAL: ULP block size %u does not fit this server (%u)\n", (unsigned)blk_sz, (unsigned)BLK_SZ);
        fflush(stdout);
        vTaskDelete(NULL);
    }
#if defined(BLK_DEBUG)
    printf("blksrv up: mem=0x%08x blkoff=%u mb=0x%08x blksz=%u\n",
           (unsigned)ulp_repl_mem_addr, (unsigned)ulp_repl_blk_off,
           (unsigned)ulp_repl_mb_addr, (unsigned)blk_sz);
    fflush(stdout);
#endif
#if defined(BLK_DEBUG)
    uint32_t seen = 0;
#endif
    for (;;) {
        /* GUARDRAIL: service a request only on a FRESH edge of the ULP's outstanding-request flag (or when a Forth
         * verb raised repl_blk_req). The naive version - "service whatever blk_out advertises" - was measured twice
         * wrong: (1) when this task is stalled past the ULP's BLKWAIT, the ULP returns BK_NOSERVER (-3) and leaves
         * blk_out set, so the late service still ADOPTED the image the machine had been told it does not have
         * ("img: adopted ... entry 1280" after a -3); (2) with blk_out set for ever after that timeout, the naive
         * task re-serviced the same stale request continuously and flooded the console.
         * An edge cannot be missed: this task polls every FreeRTOS tick (~10 ms) and BLKWAIT is ~845 ms measured. */
        int out_now = (int)ulp_repl_blk_out;      /* read once: the other core clears it when it has the answer */
        int fresh = out_now && !blk_out_prev;     /* a request this task actually SAW arrive */
        blk_out_prev = out_now;
        if (fresh) edge_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
        if (ulp_repl_blk_req || fresh) {
                if (stall_ms) { vTaskDelay(pdMS_TO_TICKS(stall_ms)); stall_ms = 0; }
#if defined(BLK_DEBUG)
            if (seen < 3) {
                volatile uint32_t *dbg = (volatile uint32_t *)(ULP_RAM_BASE + ulp_repl_mb_addr);
                printf("blksrv: req #%u blk=%u op=%u sum=%u\n", (unsigned)++seen,
                       (unsigned)dbg[0], (unsigned)dbg[1], (unsigned)dbg[3]);
                fflush(stdout);
            }
            seen++;
#endif
            volatile uint32_t *mb = (volatile uint32_t *)(ULP_RAM_BASE + ulp_repl_mb_addr);
            (void)0;
            volatile uint8_t  *buf = (volatile uint8_t *)(ULP_RAM_BASE + ulp_repl_mem_addr + ulp_repl_blk_off);
            uint32_t blk = mb[0], op = mb[1];
            if (blk >= BLK_N) {
                /* GUARDRAIL: send the MAGNITUDE of the ULP's negative BK_* code, because blk_xfer decodes a
                 * nack as `(i32)(0u - st)`. This was 2, which decoded as -2 = BK_BUSY, so "no such block"
                 * arrived at Forth as "server busy" and the operator got a misleading name for a range
                 * error. 5 decodes as BK_RANGE, which is what it is. */
                mb[2] = 5;                       /* nack: no such block -> BK_RANGE */
            } else if (op == 3u) {               /* LOAD IMAGE: validate, copy into mem[], hand back the entry xt */
                /* GUARDRAIL: this is the ONLY safe place to write mem[] from the main core. The ULP asked for it and
                 * is spinning inside blk_xfer waiting for the answer, so it is provably not fetching tokens from the
                 * region being written. A console command cannot make that promise (that is why `#l` is retired).
                 * GUARDRAIL: four named refusals, coarse codes to the ULP (which has names for 4/5/6) and a precise
                 * line to the console, because a binary load that "mostly works" executes garbage: the image carries
                 * absolute addresses.
                 *   magic/geometry    -> 5 (BK_RANGE)
                 *   sealed pointers   -> 5 (BK_RANGE)   code base and header base must match THIS machine
                 *   resident sum      -> 4 (BK_CRC)     the dictionary the image was built on
                 *   image sum         -> 4 (BK_CRC)     the bytes in the store
                 *   header collision  -> 6 (BK_BUFOVER) a pasted header must not shadow a resident name */
                const uint8_t *desc = blkfile[blk];
                uint8_t *mi = (uint8_t *)(ULP_RAM_BASE + ulp_repl_mem_addr);
                uint32_t age = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS) - edge_ms;
                if (age > 400u) {          /* 400 ms < BLKWAIT ~845 ms: past this the ULP has certainly given up */
                    /* GUARDRAIL: answer the ULP FIRST, print second. The ULP is blocked on this word, and stdout can
                     * stall for milliseconds on the USB console - measured as 50 adoption cycles where an op-3 answer
                     * arrived too late and the cycle test failed. The console must never sit between the work and the
                     * answer. */
                    mb[3] = 0; mb[2] = 5;
                    printf("img: REFUSED stale request (%u ms old, the ULP has given up) - nothing applied\n",
                           (unsigned)age);
                    goto img_done;
                }
                unsigned cl = (unsigned)desc[3] | ((unsigned)desc[4] << 8);
                unsigned hl = (unsigned)desc[5] | ((unsigned)desc[6] << 8);
                unsigned cs = (unsigned)desc[7] | ((unsigned)desc[8] << 8);
                unsigned hs = (unsigned)desc[9] | ((unsigned)desc[10] << 8);
                unsigned psum = (unsigned)desc[11] | ((unsigned)desc[12] << 8);
                unsigned rsum = (unsigned)desc[13] | ((unsigned)desc[14] << 8);
                unsigned entry = (unsigned)desc[15] | ((unsigned)desc[16] << 8);
                unsigned top = (unsigned)ulp_repl_blk_off;
                unsigned vhere = (unsigned)mi[4] | ((unsigned)mi[5] << 8);
                unsigned vseal = (unsigned)mi[12] | ((unsigned)mi[13] << 8);
                uint32_t nack = 0; int bad = 0, answered = 0; unsigned k2;
                if (desc[0] != 'F' || desc[1] != 'I' || desc[2] != 2 || cl == 0u || hl == 0u
                    || hl % 3u != 0u || cs < 52u || hs <= cs || hs + hl > top) {
                    nack = 5; bad = 1; mb[3] = 0; mb[2] = 5; answered = 1; printf("img: REFUSED bad descriptor (magic/version/geometry)\n");
                }
                if (!bad && (cs != vhere || hs + hl != vseal)) {
                    nack = 5; bad = 1; mb[3] = 0; mb[2] = 5; answered = 1;
                    printf("img: REFUSED sealed pointers moved (image built on HERE %u LATEST %u, this machine has %u and %u)\n",
                           cs, hs + hl, vhere, vseal);
                }
                if (!bad) {
                    unsigned rs = 0;
                    for (k2 = 52u; k2 < cs; k2++) rs = (rs + mi[k2]) & 0xffffu;
                    for (k2 = hs + hl; k2 < top; k2++) rs = (rs + mi[k2]) & 0xffffu;
                    if (rs != rsum) { nack = 4; bad = 1; mb[3] = 0; mb[2] = 4; answered = 1; printf("img: REFUSED resident dictionary changed (sum %u, built on %u)\n", rs, rsum); }
                }
                if (!bad) {
                    unsigned b2 = blk, o2 = 20, s2 = 0;
                    for (k2 = 0; k2 < cl + hl; k2++) {
                        s2 = (s2 + blkfile[b2][o2]) & 0xffffu;
                        if (++o2 == blk_sz) { o2 = 0; b2++; }
                    }
                    if (b2 >= BLK_N || s2 != psum) { nack = 4; bad = 1; mb[3] = 0; mb[2] = 4; answered = 1; printf("img: REFUSED image corrupt (sum %u, descriptor %u)\n", s2, psum); }
                }
                if (!bad) {
                    unsigned b2 = blk, o2 = 20 + cl, k3, j, hb[3], coll = 0;
                    while (o2 >= blk_sz) { o2 -= blk_sz; b2++; }
                    for (k3 = 0; k3 + 8 < hl; k3 += 3) {          /* +8: skip the last two entries, they are anchors */
                        for (j = 0; j < 3; j++) hb[j] = blkfile[b2 + (o2 + j) / blk_sz][(o2 + j) % blk_sz];
                        {
                            unsigned ih = ((unsigned)hb[2] << 4) | ((unsigned)hb[1] >> 4), r3;
                            for (r3 = hs + hl; r3 + 2 < top; r3 += 3) {
                                unsigned rh = ((unsigned)mi[r3 + 2] << 4) | ((unsigned)mi[r3 + 1] >> 4);
                                if (rh == ih) { if (!coll) { mb[3] = 0; mb[2] = 6; answered = 1; printf("img: REFUSED name collision, header hash %u shadows a resident %u\n", ih, r3); } coll = ih; }
                            }
                        }
                        o2 += 3;
                        while (o2 >= blk_sz) { o2 -= blk_sz; b2++; }
                    }
                    if (coll) { nack = 6; bad = 1; }
                }
                if (!bad) {
                    unsigned b2 = blk, o2 = 20;
                    for (k2 = 0; k2 < cl + hl; k2++) {
                        mi[cs + k2] = blkfile[b2][o2];
                        if (++o2 == blk_sz) { o2 = 0; b2++; }
                    }
                    mi[4] = (uint8_t)((cs + cl) & 0xffu); mi[5] = (uint8_t)(((cs + cl) >> 8) & 0xffu);
                    mi[6] = 0; mi[7] = 0;
                    mi[8] = (uint8_t)(hs & 0xffu); mi[9] = (uint8_t)((hs >> 8) & 0xffu);
                    mi[10] = 0; mi[11] = 0;
                    /* the entry xt rides back in the block window: 4 bytes, little-endian */
                    buf[0] = (uint8_t)(entry & 0xffu); buf[1] = (uint8_t)((entry >> 8) & 0xffu);
                    buf[2] = 0; buf[3] = 0;
                    mb[3] = 0; mb[2] = 1u;      /* answer FIRST - see the GUARDRAIL above */
                    printf("img: adopted code %u + hdr %u from block %u, entry %u\n", cl, hl, (unsigned)blk, entry);
                    answered = 1;
                }
                if (!answered) { mb[3] = 0; mb[2] = bad ? nack : 1u; }
img_done:   ;
            } else if (op == 0u) {               /* READ */
                uint32_t s = 0; int i;
                for (i = 0; i < (int)blk_sz; i++) { buf[i] = blkfile[blk][i]; s += blkfile[blk][i]; }
                /* GUARDRAIL: a checksum disagreement between the two cores has three possible owners —
                 * the store, the copy, or the check — and the board transcript cannot tell them apart.
                 * Print what this core actually has AFTER the copy, so the ULP's complaint has a number
                 * to compare against instead of being an argument about who is wrong. */
#if defined(BLK_DEBUG)
                if (seen <= 6) {
                    printf("blksrv: READ blk=%u file=%u,%u buf=%u,%u sum=%u\n", (unsigned)blk,
                           (unsigned)blkfile[blk][0], (unsigned)blkfile[blk][1],
                           (unsigned)buf[0], (unsigned)buf[1], (unsigned)(s & 0xffffu));
                    fflush(stdout);
                }
#endif
                mb[3] = s & 0xffffu;
                mb[2] = 1u;
            } else {                             /* WRITE */
                uint32_t s = 0; int i;
                for (i = 0; i < (int)blk_sz; i++) s += buf[i];
                if ((s & 0xffffu) != mb[3]) {
                    /* GUARDRAIL: same decoding rule as the range nack above: 0xFFFFFFFC decodes as +4 (not
                     * -4), so a checksum mismatch would have reached Forth as an unnamed positive status. 4
                     * decodes as BK_CRC. This path is not covered by the host tests (they use the engine's
                     * fake server), so the rule, not a test, is what keeps it honest. */
                    mb[2] = 4;                   /* nack: checksum mismatch -> BK_CRC (-4) */
                } else {
                    for (i = 0; i < (int)blk_sz; i++) blkfile[blk][i] = buf[i];
                    mb[2] = 1u;
                }
            }
        }
        /* Once, after the ULP has done real work, report the painted high-water mark.
         * GUARDRAIL: report it THROUGH THE ULP'S CONSOLE by injecting a Forth line into the command ring.
         * printf here goes to a console that emits nothing on this board (/dev/ttyACM0 reads 0 bytes), so the
         * measurement had no channel at all. The ring is the only visible console, and it needs no ULP bytes. */
#if defined(CANARY)
        { static int reported; static uint32_t ticks;
          if (!reported && ++ticks == 4000u) {
              char line[24]; int n;
              uint32_t h = ulp_repl_cmd_head, tl = ulp_repl_cmd_tail, space, k;
              n = snprintf(line, sizeof line, "%u .\r", (unsigned)canary_used());
              space = CMD_SIZE - (h - tl);
              if (n > 0 && (uint32_t)n <= space) {
                  for (k = 0; k < (uint32_t)n; k++) CMD_BYTES[(h + k) & CMD_MASK] = (uint8_t)line[k];
                  ulp_repl_cmd_head = h + (uint32_t)n;
                  reported = 1;
              }
              /* if the ring is full this retries next tick rather than losing the number silently */
          } }
#endif
        vTaskDelay(1);                            /* 1 ms: the ULP's poll is bounded, so keep this short */
    }
}

/* GUARDRAIL: declared here because app_main creates the server before this file defines it — an
 * undeclared-call error, which is the good kind: it fails at compile time instead of linking a task
 * that never starts. */

static void block_task(void *arg);

void app_main(void)
{
    /* Watchdog first (P06): a hung bridge takes the console *and* the flashing port with it. */
    esp_task_wdt_config_t wdt = { .timeout_ms = 5000, .idle_core_mask = 0, .trigger_panic = true };
    esp_task_wdt_reconfigure(&wdt);

    uart_config_t cfg = {
        .baud_rate = CONSOLE_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(CONSOLE_UART, 1024, 1024, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(CONSOLE_UART, &cfg));

    printf("\nboot: ulp forth bridge, %u B image\n", (unsigned)(bin_end - bin_start));
    printf("type Forth at the prompt; 'picocom -b %d /dev/ttyACM1'\n", CONSOLE_BAUD);
    fflush(stdout);

    ESP_ERROR_CHECK(ulp_riscv_load_binary(bin_start, (size_t)(bin_end - bin_start)));

    /* Loud before anything else: if these disagree, every byte the user types is written to the wrong
     * place in the coprocessor's memory and the symptom looks like Forth corruption, not like a bug in
     * a size constant. Refuse to run the bridge at all rather than serve a broken console. */
    if (ulp_repl_cmd_bytes != CMD_SIZE || ulp_repl_out_bytes != OUT_SIZE) {
        printf("FATAL: ring size mismatch — ULP cmd=%u out=%u, host cmd=%u out=%u\n",
               (unsigned)ulp_repl_cmd_bytes, (unsigned)ulp_repl_out_bytes,
               (unsigned)CMD_SIZE, (unsigned)OUT_SIZE);
        fflush(stdout);
        for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
    }
    /* 1 000 ticks at the measured 6.46 us/tick = 6 460 us. The API takes microseconds. */
    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, 6460));
#if defined(CANARY)
    canary_paint();                      /* before the ULP runs: the only moment the stack is untouched */
#endif
    ESP_ERROR_CHECK(ulp_riscv_run());
    ESP_LOGI(TAG, "ulp armed");

    /* GUARDRAIL: report the ULP's own wake counter before handing over. Without it, a silent console is
     * ambiguous — "the coprocessor never started" and "the coprocessor started and did nothing" look
     * identical from the port, and the counterfactual test in P41 is worthless if it cannot tell them
     * apart. This line is the proof that the ULP is alive; its absence is a different failure. */
    vTaskDelay(pdMS_TO_TICKS(500));
    printf("ulp woke %u times\n", (unsigned)ulp_repl_wake_count);
    fflush(stdout);

    /* GUARDRAIL: console_task installs the UART driver, so it must exist before anything that prints at
     * startup — created the other way round, the server's own "blk size" diagnostic went nowhere and a
     * size of 0 looked like a silent protocol failure. The server still gets a higher priority, so it can
     * never be starved by the pump. */
    xTaskCreate(console_task, "console", 4096, NULL, 10, NULL);
    BaseType_t ok = xTaskCreate(block_task, "blocksrv", 2048, NULL, 12, NULL);
    printf("blocksrv %s\n", ok == pdPASS ? "up" : "FAILED"); fflush(stdout);
}
