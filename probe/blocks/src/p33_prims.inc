/* P33: P31's generated primitive table, unchanged, plus the one primitive a visible block layer
 * cannot be Forth: the request/bounded-wait/response handshake over the mailbox.
 * GUARDRAIL: the extra entry lives in this wrapper, not inside p31_prims.inc — editing the
 * generated table would change what every earlier variant's row means (P31 kept it one entry per
 * line precisely so a primitive could be priced by ID). */
#include "p31_prims.inc"
#if defined(P33_BLOCK)
X(BLKXFER,"BLKXFER",0)
#endif

#if defined(P43_TASKS)
/* P43: the two entries that make R4 reachable. State was already paid for (tsk[] is in .bss); these
 * are the calls that were missing, which is why --gc-sections had deleted vm_task_init entirely. */
X(SPAWN,"SPAWN",0)
#endif

#if defined(BLKPRIM)
/* EXP_BLK: the operator-facing block words, as C primitives. Same names, same stack effects, same
 * named errors as the 530 B Forth layer they replace. */
X(BLOCK,"BLOCK",0)
X(UPDATE,"UPDATE",0)
X(SAVE,"SAVE",0)
#endif
