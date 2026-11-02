/* P33: P31's generated primitive table, unchanged, plus the one primitive a visible block layer
 * cannot be Forth: the request/bounded-wait/response handshake over the mailbox.
 * GUARDRAIL: the extra entry lives in this wrapper, not inside p31_prims.inc — editing the
 * generated table would change what every earlier variant's row means (P31 kept it one entry per
 * line precisely so a primitive could be priced by ID). */
#include "p31_prims.inc"
#if defined(P33_BLOCK)
X(BLKXFER,"BLKXFER",0)
#endif

#if defined(BLKPRIM)
/* R5: the operator-facing block words as C primitives — same names, same stack effects, same named
 * errors as the 530 B Forth layer they replace. GUARDRAIL: these three were MISSING here while the case
 * bodies and the p_blk_* functions existed, so BLOCK was simply an unknown word on the chip while every
 * unit test of the layer passed. A primitive needs BOTH an X entry (the header) and a case (the body);
 * either one alone compiles, links and looks fine until the operator types the word. */
X(BLOCK,"BLOCK",0)
X(UPDATE,"UPDATE",0)
X(SAVE,"SAVE",0)
#endif

#if defined(P43_TASKS)
/* P43: the two entries that make R4 reachable. State was already paid for (tsk[] is in .bss); these
 * are the calls that were missing, which is why --gc-sections had deleted vm_task_init entirely. */
X(SPAWN,"SPAWN",0)
#endif
/* P58: a literal that fits a halfword is 4 B, not 6 B. The engine reads the operand with rd16_paged() and
 * steps 2, so the compiled code area shrinks by 2 B for every small literal in the image — and app space is
 * the code area's mirror image. Appended HERE, after every other entry, so all existing ids are unchanged:
 * tokens are PRIM_TAG - 2*id, so inserting one in the middle would renumber the whole vocabulary. */
X(LIT2,"LIT2",0)

#if defined(OVL_LOAD)
/* GUARDRAIL: the entry goes LAST, after LIT2, for the same reason LIT2 did: tokens are PRIM_TAG - 2*id, so
 * inserting a primitive in the middle renumbers the whole vocabulary and every baked xt shifts silently.
 * A primitive needs BOTH this X entry (the header) and a case in p33_cases.inc (the body); either one alone
 * compiles, links and looks fine until the operator types the word. */
X(LOAD,"LOAD",0)
#endif
