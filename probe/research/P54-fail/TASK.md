# TASK — Idea 2: do the error/message call sites cost bytes?

Read `../SHARED_BRIEF.md` first.

## The claim to test
There are **20** `err(ERR_*)`/`msg(MSG_*)` call sites (14 `src/uforth.c`, 6 `src/ulp_repl.c`). A previous guess
said ~120 B is reclaimable. **That number is unmeasured and is barred from your report unless you measure it.**

## Steps
1. **Measure before changing anything.** How many bytes do those 20 sites actually occupy, including argument
   setup, the error-flag store, and the call itself? Use `objdump -d` on the twin ELF and count, and
   `nm -S --size-sort` for symbol sizes. Give a per-site cost distribution, not just a total.
2. Look for what is genuinely duplicated: repeated epilogues, PAD/format setup, repeated `errf = 1` stores,
   repeated code stores.
3. Try each shape and measure Δ`.text`:
   (a) one `__attribute__((noinline))` helper taking the code in a register;
   (b) a `noreturn` helper;
   (c) hoisting whatever shared tail exists.
   Negative results are results — report them.
4. State the trade in bytes **and** in dispatch cost (a call adds a frame + `ret` per site).
5. `tests/run.sh` must be green. The suite pins error output: `deep.fs` (`ERR_STACK`), `addr.fs` (`0000`),
   `ntsk.fs` (`ERR_TASKS`), the unknown-code check. The whole point of one-byte codes is that **diagnostics do
   not change** — verify the messages are byte-identical, not merely still an error.

## Deliverable
`FINDINGS.md`: measured per-site cost actually observed; variants table; verdict (including "not worth it");
diff. Do not repeat the 120 B guess unless your measurement supports it.
