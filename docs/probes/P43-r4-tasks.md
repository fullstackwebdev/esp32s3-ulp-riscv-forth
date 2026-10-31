# P43 — Does multi-tasking (R4) run on the chip?

| | |
|---|---|
| **Question** | `tsk[]` (420 B) is allocated and `vm_switch` is linked, but `vm_task_init` was eliminated by `--gc-sections`: nothing could create a task. Can R4 be reachable, and does it survive a REPL above it? |
| **Answer** | Yes. Two tasks interleave mid-body (**1324**), three tasks use three slots (**131242**), and the REPL answers correctly before, between and after. |
| **Cost** | **+496 B `.text`**, +10 B dictionary; app space 912 → **354 B** (`MEMSZ` 2 048 → 1 500). Pool 7 842 / 7 856. |
| **Time** | 15 min budgeted; five wrong turns taken — see below |

## What was missing, and what it took

1. **`SPAWN` primitive** — parses a name, resolves the xt, takes a free slot, calls `vm_task_init`. Without it the
   whole task layer is dead code (which is why the linker had deleted it).
2. **A driver** — `vm_run_tasks()` existed and was never called. It now runs once per wake from `main()`, after
   `drain_cmd` has published its tail.
3. **Retire path** — `vm_task_leave` called `pl_halt(0)` on the last task, correct when tasks were the only driver,
   fatal with a REPL above them. It returns to C with `cur = -1`.
4. **The baked dictionary** — a new primitive needs `image.h` regenerated on the host
   (`gcc -DHOST -DP43_TASKS … && ./host -d src/image.h src/p39_prelude.fs src/line.fs`), or `SPAWN` answers `SPAWN?`
   with the primitive plainly present in the source.

## Four wrong turns, all recorded as findings

* stepping tasks **inside `drain_cmd`** (third instance of putting code inside the path it depends on) → replayed
  command bytes;
* a **136 B `VM outer` local** to save the live machine → C stack on top of a 244 B worst case against a 320 B
  reserve; replaced by a loud precondition (clean prompt, else refuse);
* the refusal printed **once per wake** — hundreds of times; now reports once and retires the pending task;
* and the corruption that outlived all of it was **the ring sizes duplicated in two files** (F-74), not R4 at all.

## Verified

```
: TA 1 . PAUSE 2 . ;   : TB 3 . PAUSE 4 . ;
SPAWN TA SPAWN TB            -> ok / 1324
SPAWN TA SPAWN TB SPAWN TA   -> ok / 131242
2 3 + .                      -> 5 ok
5 6 SPAWN TA                 -> ok / tasks need an empty stack   (once)
42 .                         -> 42 ok
```
