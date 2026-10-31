/* p27_test.c — does a task switch actually switch the machine?
 *
 * Build: gcc -DHOST -std=c99 -Wall -Wextra -o p27_test p27_test.c && ./p27_test
 *
 * Four probes, each against a number computed on the host by p27_expect.py from the
 * scheduling rule and the Forth source text (never from this program's output):
 *   (a) three-task interleaving: switch order and per-task counts
 *   (b) PAUSE in the middle of a colon word, resumed once: value and stacks vs no-PAUSE
 *   (c) PAUSE inside DO inside a colon word, resumed once per iteration
 *   (d) a page fault at the same positions: same numbers, and the same vm_switch() call
 */
#define main uforth_unused_main
#include "uforth.c"
#undef main

#include <stdio.h>
#include <string.h>

static int fails, passes;
static char tracelog[4096];
static u16 cbase;                /* address of the three counter cells */

static void check(int cond, const char *name, const char *detail)
{
    if (cond) { passes++; printf("  PASS  %s\n", name); }
    else { fails++; printf("  FAIL  %s   [%s]\n", name, detail ? detail : ""); }
}

static void die(const char *what) { printf("FATAL: %s\n", what); fails++; }

static void trace_cb(int from, int to)
{
    char b[24];
    snprintf(b, sizeof b, "%c>%c ", from < 0 ? '-' : 'A' + from, to < 0 ? '-' : 'A' + to);
    strncat(tracelog, b, sizeof tracelog - strlen(tracelog) - 1);
}

static void reset_all(void)
{
    int k;
    memset(tsk, 0, sizeof tsk);
    V = &vm_live;
    vm_live.SP = 0; vm_live.RSP = 0; vm_live.W = 0; vm_live.IP = 0;
    for (k = 0; k < SD; k++) { vm_live.DS[k] = 0; vm_live.RS[k] = 0; }
    errf = 0; wr32(V_STATE, 0);
    cur = -1;
    vm_switches = vm_sw_pause = vm_sw_fault = vm_faults = 0;
    vm_sw_taskexit = vm_sw_first = 0;
    vm_depth = vm_max_depth = 0;
    vm_faults_left = 0;
    vm_trace = trace_cb;
    tracelog[0] = 0;
}

static void line(const char *s)
{
    size_t n = strlen(s);
    if (n >= TIBSZ) { die("test line longer than TIBSZ"); return; }
    memcpy(tib, s, n); tl = (u8)n; ti = 0;
    interpret();
}

/* FNV-1a over the whole machine image: the two stacks and their pointers. Equal digests
 * mean the switch left the machine byte-identical to the run that never switched. */
static u32 digest(void)
{
    u32 h = 2166136261u; int k;
    u8 *b = (u8 *)&vm_live;
    for (k = 0; k < (int)sizeof vm_live; k++) { h ^= b[k]; h *= 16777619u; }
    return h;
}

/* xt of a word by compiling `' NAME` and reading the data stack */
static u16 xt_of(const char *name)
{
    char buf[64];
    snprintf(buf, sizeof buf, "' %s", name);
    V = &vm_live; vm_live.SP = 0;
    line(buf);
    if (errf || vm_live.SP != 1) { printf("  (xt lookup failed for %s)\n", name); return 0; }
    return (u16)vm_live.DS[0];
}

/* GUARDRAIL: do not locate a token by scanning the body in 2-byte steps — a LIT *operand*
 * can equal the token id, and the first version of this test "found" PAUSE 4 bytes past the
 * real one and failed a good switch. Assert at the saved pointer instead: the token before
 * the resume ip must BE the PAUSE primitive. */
/* GUARDRAIL: two traps here, both hit on the first attempt. (1) A token in the dictionary is
 * an xt (an address), not a primitive id — compare with xt_of("PAUSE"), never with P_PAUSE.
 * (2) The saved pair is P03d's post-fetch window of the NEXT dispatch, so the PAUSE token is
 * FOUR bytes below the saved ip (w sits at ip-2, its continuation is ip). */
static int paused_right_after(u16 xt, u16 ipv, u16 pxt)
{
    return ipv > xt + 4 && ipv < rd32(V_HERE) && rd16((u32)ipv - 4) == pxt;
}

static u16 var_addr(const char *name)
{
    V = &vm_live; vm_live.SP = 0;
    line(name);
    if (errf || vm_live.SP != 1) { printf("  (address lookup failed for %s)\n", name); return 0; }
    return (u16)vm_live.DS[0];
}

/* GUARDRAIL: the injected-fault budget must be armed AFTER reset_all(), which zeroes it —
 * arming it before the run silently disabled every injected fault and the fault test passed
 * for the wrong reason (0 faults, same numbers). */
static void run_one_task(u16 xt, u32 faults)
{
    reset_all();
    vm_faults_left = faults;
    vm_task_init(0, xt);
    vm_run_tasks();
}

int main(void)
{
    u16 ta, tb, tc, b0, b1, n0, n1, b1f, n1f;
    u32 dg_b0, dg_n0;

    boot_init();
    if (load("boot_min.fs")) { printf("FATAL: boot_min.fs\n"); return 2; }

    reset_all();
    line("CREATE C 0 , 0 , 0 ,");
    line(": INC ( a -- ) DUP @ 1 + SWAP ! ;");
    if (errf) die("helpers did not compile");
    cbase = var_addr("C");

    /* ---------- (a) three tasks, round-robin, quantum = one PAUSE ---------- */
    printf("\n== (a) three-task interleaving\n");
    line(": TA 5 0 DO C INC PAUSE LOOP ;");
    line(": TB 3 0 DO C 4 + INC PAUSE LOOP ;");
    line(": TC 4 0 DO C 8 + INC PAUSE LOOP ;");
    if (errf) die("(a) task words did not compile");
    ta = xt_of("TA"); tb = xt_of("TB"); tc = xt_of("TC");

    reset_all();
    vm_task_init(0, ta); vm_task_init(1, tb); vm_task_init(2, tc);
    vm_run_tasks();

    printf("A-ORDER: %s\n", tracelog);
    printf("A-COUNTS: A=%u B=%u C=%u\n",
           rd32(cbase + 0), rd32(cbase + 4), rd32(cbase + 8));
    printf("C-STACK: max C call depth into the interpreter over the whole 3-task run = %d\n",
           vm_max_depth);
    printf("A-SWITCHES: total=%u pause=%u fault=%u taskexit=%u\n",
           vm_switches, vm_sw_pause, vm_sw_fault, vm_sw_taskexit);
    check(rd32(cbase + 0) == 5 && rd32(cbase + 4) == 3 && rd32(cbase + 8) == 4,
          "(a) per-task counts are 5 / 3 / 4", "see A-COUNTS");
    check(strncmp(tracelog, "->A A>B B>C C>A", 15) == 0,
          "(a) switch order starts ->A A>B B>C C>A", tracelog);
    check(vm_max_depth == 1,
          "(a) 3 tasks, 12 pre-emptions, 1 C frame: the switch never unwinds the C stack", "");
    {
        u32 total = vm_sw_pause + vm_sw_fault + vm_sw_taskexit + vm_sw_first;
        char d[128];
        snprintf(d, sizeof d, "total=%u pause=%u fault=%u taskexit=%u first=%u",
                 vm_switches, vm_sw_pause, vm_sw_fault, vm_sw_taskexit, vm_sw_first);
        check(total == vm_switches, "(a) every switch is a PAUSE, a fault, a task exit, or the first entry", d);
    }

    /* ---------- (b) PAUSE in the middle of a colon word, resumed once ---------- */
    printf("\n== (b) suspend mid-word\n");
    line(": B0 7 3 * 5 + DUP * ;");
    line(": B1 7 3 * 5 + PAUSE DUP * ;");
    if (errf) die("(b) words did not compile");
    b0 = xt_of("B0"); b1 = xt_of("B1");
    run_one_task(b0, 0);
    dg_b0 = digest();
    {
        u32 v0 = vm_live.DS[0], sp0 = vm_live.SP, rsp0 = vm_live.RSP;
        printf("B0: value=%u sp=%u rsp=%u digest=0x%08x (no PAUSE)\n", v0, sp0, rsp0, dg_b0);

        run_one_task(b1, 0);
        printf("B1: value=%u sp=%u rsp=%u digest=0x%08x pauses=%u\n",
               vm_live.DS[0], vm_live.SP, vm_live.RSP, digest(), vm_sw_pause);
        check(vm_live.DS[0] == v0 && v0 == 676, "(b) mid-word PAUSE yields the same value 676", "");
        check(digest() == dg_b0, "(b) machine image byte-identical to the no-PAUSE run", "");
        check(vm_sw_pause == 1, "(b) exactly one suspend/resume", "");

        /* the resume point must be INSIDE the word, one token past PAUSE */
        {
            char d[160];
            u16 pxt = xt_of("PAUSE");
            snprintf(d, sizeof d, "xt=%u saved w=%u ip=%u rd16(ip-4)=%u(=PAUSE xt %u)",
                     b1, tsk[0].vm.W, tsk[0].vm.IP, rd16((u32)tsk[0].vm.IP - 4), pxt);
            check(paused_right_after(b1, tsk[0].vm.IP, pxt),
                  "(b) saved ip is one token past PAUSE, inside the word body", d);
            check(tsk[0].vm.IP != 0 && tsk[0].vm.W == rd16((u32)tsk[0].vm.IP - 2),
                  "(b) saved w is the next token of the same word, not the caller", d);
        }
    }

    /* ---------- (c) PAUSE inside DO inside a colon word ---------- */
    printf("\n== (c) suspend inside DO inside a word\n");
    line(": N0 0 5 0 DO I + LOOP ;");
    line(": N1 0 5 0 DO I + PAUSE LOOP ;");
    if (errf) die("(c) words did not compile");
    n0 = xt_of("N0"); n1 = xt_of("N1");
    run_one_task(n0, 0);
    dg_n0 = digest();
    {
        u32 v0 = vm_live.DS[0];
        printf("N0: value=%u sp=%u rsp=%u digest=0x%08x (no PAUSE)\n",
               v0, vm_live.SP, vm_live.RSP, dg_n0);
        run_one_task(n1, 0);
        printf("N1: value=%u sp=%u rsp=%u digest=0x%08x pauses=%u\n",
               vm_live.DS[0], vm_live.SP, vm_live.RSP, digest(), vm_sw_pause);
        check(v0 == 10 && vm_live.DS[0] == v0, "(c) PAUSE in a DO body yields the same 10", "");
        check(digest() == dg_n0, "(c) machine image byte-identical to the no-PAUSE run", "");
        check(vm_sw_pause == 5, "(c) resumed once per loop iteration (5)", "");
    }

    /* ---------- (d) a page fault at the same positions ---------- */
    printf("\n== (d) page fault at the same positions\n");
    line(": B1F 7 3 * 5 + FAULT DUP * ;");
    line(": N1F 0 5 0 DO I + FAULT LOOP ;");
    if (errf) die("(d) words did not compile");
    b1f = xt_of("B1F"); n1f = xt_of("N1F");
    run_one_task(b1f, 1);
    {
        u32 dv = vm_live.DS[0], dsp = vm_live.SP, drsp = vm_live.RSP;
        printf("B1F: value=%u sp=%u rsp=%u faults=%u fault_switches=%u\n",
               dv, dsp, drsp, vm_faults, vm_sw_fault);
        check(dv == 676 && digest() == dg_b0,
              "(d) fault at (b)'s position: same 676 and the same machine image", "");

        run_one_task(n1f, 5);
        printf("N1F: value=%u sp=%u rsp=%u faults=%u fault_switches=%u\n",
               vm_live.DS[0], vm_live.SP, vm_live.RSP, vm_faults, vm_sw_fault);
        check(vm_live.DS[0] == 10 && digest() == dg_n0,
              "(d) fault inside the DO body: same 10 and the same machine image", "");
        check(vm_switches == vm_sw_pause + vm_sw_fault + vm_sw_taskexit + vm_sw_first,
              "(d) fault retries and PAUSE share one vm_switch()", "");
        check(vm_sw_fault > 0 && vm_sw_pause == 0,
              "(d) the fault path needed no PAUSE switch to reproduce the result", "");
    }

    printf("\n(TASK RECORD SIZE: %u B = VM %u B + entry 2 + state 1, padded)\n",
           (unsigned)sizeof(TSK), (unsigned)sizeof(VM));
    printf("\n%d passed, %d failed\n", passes, fails);
    return fails ? 1 : 0;
}
