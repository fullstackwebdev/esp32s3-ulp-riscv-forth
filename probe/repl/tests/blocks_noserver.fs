\ R5: a block nobody answers must time out BY NAME and leave the machine usable.
\ GUARDRAIL: after a timeout blk_out stays set on purpose (a late answer must not be raced into the next
\ request's buffer), so the NEXT block call answering ERR_BUSY is the documented consequence, not a bug.
\ This file therefore runs in its own process: one wedged request would poison every later test.
5 BLOCK .
2 3 + .
0 BLOCK .
