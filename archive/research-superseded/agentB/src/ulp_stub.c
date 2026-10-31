/* ulp_stub.c — the counterfactual image: a ULP that runs and does no Forth.
 *
 * Built only with REPL_ULP_STUB=1. It exports the same ring symbols the HP bridge touches, so the main
 * core links and pumps exactly as it always does, and then it wakes, counts, and returns without reading
 * a single command byte.
 *
 * What this proves when flashed: if the console still answers, the main core was doing Forth all along.
 * If the console goes silent while `ulp woke N times` keeps advancing, then the interpreter, the echo and
 * the prompt live only on the coprocessor. Silence would otherwise be ambiguous — it could just mean the
 * ULP never started — so the wake counter is what makes the negative result mean something.
 *
 * GUARDRAIL: the ring sizes must match ulp_repl.c exactly (128 B command, 256 B output). A stub with
 * different sizes still links and still goes silent, but then the silence proves nothing about the real
 * image's indexing — the counterfactual has to differ in exactly one thing: the evaluator.
 */
#include <stdint.h>

volatile uint32_t repl_cmd[32];        /* 128 B, as in ulp_repl.c */
volatile uint32_t repl_out[64];        /* 256 B, as in ulp_repl.c */
volatile uint32_t repl_cmd_head;
volatile uint32_t repl_cmd_tail;
volatile uint32_t repl_out_head;
volatile uint32_t repl_out_tail;
volatile uint32_t repl_wake_count;

int main(void)
{
    /* GUARDRAIL: touch every ring symbol or `--gc-sections` drops it as unused data; the IDF map generator
     * then exports no `ulp_*` for it and the HP side fails to build with "'ulp_repl_cmd' undeclared", which
     * reads like a CMake problem and is the linker doing its job. A stub that does nothing still has to
     * look like it uses what it defines. */
    volatile uint32_t keep;
    keep = repl_cmd[0];
    keep = repl_out[0];
    keep = repl_cmd_head;
    keep = repl_cmd_tail;
    keep = repl_out_head;
    keep = repl_out_tail;
    (void)keep;

    repl_wake_count = repl_wake_count + 1u;
    return 0;                          /* halt: timer re-arms, nothing was read, nothing written */
}
