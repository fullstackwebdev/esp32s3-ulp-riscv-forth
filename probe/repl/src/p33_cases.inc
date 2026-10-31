/* P33: P31's generated case bodies, unchanged, plus BLKXFER behind -DP33_BLOCK.
 * GUARDRAIL: ( n op -- addr st ) pushes the buffer address *and* the status, so the Forth layer
 * never spells the buffer's address as a literal. A hard-coded 908 in blocks.fs would be a budget
 * line that moves whenever MEMSZ moves and would silently point into the dictionary instead. */
#include "p31_cases.inc"
#if defined(P33_BLOCK)
        case P_BLKXFER:
            b = POP(); a = POP();
            PUSH(BLKADR); PUSH((u32)blk_xfer(a, b));
            break;
#endif

#if defined(BLKPRIM)
/* R5: BLOCK / UPDATE / SAVE. GUARDRAIL: the X entries in p33_prims.inc and these cases are two halves of
 * one primitive — with only the header, the token dispatches to `default: err()`, which prints the word in
 * PAD and is indistinguishable from "unknown word" (F-107's shape again). Measured: BLOCK existed in the
 * dictionary at xt=184 with cf=67 and still answered `BLOCK?`. */
        case P_BLOCK:  p_blk_block();  break;
        case P_UPDATE: p_blk_update(); break;
        case P_SAVE:   p_blk_save();   break;
#endif

#if defined(P43_TASKS)
        case P_SPAWN: vm_spawn_name(); break;
#endif
