# ABANDONED — do not build, do not flash

This directory holds a C HP-core SX1262 receiver I started and then abandoned mid-write. It is kept, not deleted, so
the record of the wrong turn survives.

**Why it is wrong:** the whole era's requirement is that the LoRa path is *Forth* on the ULP — "a Forth word, compiled
on the chip into the ULP pool, puts a LoRa frame on 868 MHz". Writing a C peer to observe it reintroduces exactly the
split this work exists to remove, and it would have made the second board's behaviour unrepresentative of the first.

**What is used instead:** both boards run the *same* firmware (`probe/repl`, the ULP Forth REPL). The transmitter
loads `examples/apps/lora/lora1.fs`; both boards load `examples/apps/lora/lora_rx.fs` to receive, in Forth, so the
outside receiver is the same Forth driver on a second board rather than a bespoke C program.

Nothing here is built by any test or script. If it is ever revived, it must be justified against the Forth rule first.
