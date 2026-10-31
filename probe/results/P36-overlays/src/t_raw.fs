\ t_raw.fs — the dangerous case, deliberately: an entry address called with EXECUTE instead of APP.
\ Loaded last and on its own, because the outcome is whatever the stale bytes decode to.
\ GUARDRAIL: this file exists to show that the *raw* path is silent. If it ever prints a named
\ error, APP is no longer the only choke point and the guarantee in docs has to be rewritten.
." == raw xt escape (the hole) ==" CR
." seg1 directory xt: " 1 SEG-WORD . CR
." bytes at that address now: " 1 SEG-WORD RAW@ . CR
." calling it with EXECUTE: [" 1 SEG-WORD EXECUTE ." ] end, no error above if the list is empty" CR
." segment 2 still fine: " 2 APP CR
." done" CR
