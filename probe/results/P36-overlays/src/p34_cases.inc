/* P34: P31's generated case bodies, unchanged, plus FAR-XFER behind -DP34_FAR.
 * GUARDRAIL: the stack effect is ( op block -- buf st ), not ( op block -- st ): the buffer's Forth
 * address is pushed by the primitive because a literal address in a .fs file is a budget line that
 * moves whenever MEMSZ moves and would silently point into the dictionary instead (P33 learned this
 * with a hard-coded 908; P34 keeps the lesson and the probe's op/block order).
 * GUARDRAIL: b is TOS = block, a is op — reading them the other way round sends the op code as a
 * block number, and the server answers a request nobody made. */
#include "p31_cases.inc"
#if defined(P34_FAR)
        case P_FARXFER:
            b = POP(); a = POP();               /* ( op block -- ) : block is TOS */
            PUSH(FARBADR); PUSH((u32)far_xfer(b, a));
            break;
#endif
