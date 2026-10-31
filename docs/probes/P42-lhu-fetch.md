# P42 — Does a halfword token fetch pay?

| | |
|---|---|
| **Question** | Token fetch is 90.9 % of a dispatch (F-18), and `rd16(a)` is `rd8(a) \| rd8(a+1) << 8` — two loads, a shift and an or. Tokens are 16-bit and always even, so `lhu` is legal. Does one load beat two? |
| **Why it matters** | It is the only optimisation on the hottest path that is *both* cheaper in cycles and smaller in bytes. If `NEXT` does not move, the lever is memory *latency*, not instruction count — a different and more expensive line of work. |
| **Method** | Two images, identical except `rd16`; a fixed stack-neutral line interpreted 100× with `rdcycle` timing, minimum reported. |
| **Time** | 15 min budgeted |
| **Verdict** | **PASS on attempt 2: −35.2 % cycles per dispatch (1 757.75 → 1 139.25), adopted.** Attempt 1 was INVALID — see `probe/repl/probe-results/P42-RESULT.md` |

## Result (attempt 2)

| Image | 81 disp | 161 disp | cycles/dispatch |
|---|---|---|---|
| `rd8`+`rd8` | 193 928 | 334 548 | **1 757.75** |
| one `lhu` | 122 804 | 213 944 | **1 139.25** |

−618.5 cycles/dispatch. Shipping image 6 112 B, pool 7 264 B of 7 856 (+6 B). Verified on the board after adoption.

## Size half

`rd16` → single halfword load: **`.text` 4 948 → 4 936 B (−12 B)**, `rd16` section 54 → 36 B (E-052). `rd16` is
**out of line** (42 B, 11 call sites), so the byte win is one function, not eleven sites.

## Failed attempts, and what they cost

1. **`BEGIN…UNTIL` as a typed workload is void.** Compile-only words: `3 BEGIN 1- DUP 0 = UNTIL DROP .` prints `3`;
   the "1 000-iteration" run took 141 684 cycles. A benchmark that silently runs once measures nothing.
2. **Bench inside `drain_cmd()` is void.** Re-entering `interpret()` 104× mid-drain left the machine echoing without
   answering, and reported `min=567 cycles` for 100× 54 tokens with `errf=4` on a 0/1 flag.

## Next attempt (required before any verdict)

Time the workload from `main()` before the first drain; assert `ti == tl` and `errf == 0` after one iteration before
looping; count tokens with a bench-only counter in `interpret()`; use two line lengths so the per-call overhead
cancels and the slope is cycles/token.
