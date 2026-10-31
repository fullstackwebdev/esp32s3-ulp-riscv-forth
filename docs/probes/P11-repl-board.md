# P11 — The real REPL link: attach, pacing, exclusion, dead-man (board)

| | |
| --- | --- |
| Runs on | **board (exclusive)** — overwrites the firmware and needs the console port |
| Time box | **15 min**, one run, hard cap |
| Depends on | P06 (wake semantics), P10 (host line discipline) |
| Blocks | R8 acceptance items 1–3, 6–7 |
| Serves | R8 |

## Question

On the actual hardware, over `/dev/ttyACM1` at 115200: what does attaching look like, how many paced
lines survive, what does an unpaced paste actually lose, does the port refuse a second opener, and
does the dead-man timer hand the ULP back to autonomous mode when the terminal goes away?

## Given — measured already, do not re-derive

* Console on **UART0 / `/dev/ttyACM1`** (CH343), flashing on **`/dev/ttyACM0`** (native USB).
* Connected-mode period **32–64 ticks = 207–414 µs** (P05: 122.6 cycles/tick, 6.46 µs/tick, 81 cycles
  wake entry).
* Rings **128 B command / 256 B output**, pacing rule **one line per prompt byte** (P04).
* Host tool: `python3` with `pyserial` 3.5 installed; nothing else may be installed.

## Method

1. Board lock first:
   ```sh
   exec 9>probe/results/.board.lock
   flock -n 9 || { echo "BLOCKED: board busy"; exit 3; }
   ```
2. Build a **minimal** bridge, not the full feature: UART0 at 115200, a FreeRTOS task that moves bytes
   between the port and the two rings, the `0x1D` escape with one byte of lookahead, the dead-man
   timer, and a heartbeat counter the tool can read in the state line. No Forth work on the ULP side
   is needed yet — the ULP can be a stub that echoes and prints `ok` per line. **The REPL contract is
   what is under test, not the interpreter.**
3. Measure, in this order, each bounded:
   - **attach**: time from opening the port to the first prompt byte (10 samples);
   - **200 paced lines**: zero dropped output bytes, zero lost input, no duplicate lines;
   - **unpaced paste**: send 4 KB as fast as the port accepts it; record how many bytes the ULP
     actually received (it counts them), and confirm the loss is *reported*, not silent;
   - **exclusion**: open the port a second time (`pyserial`), confirm a named refusal and that the
     first session is unaffected;
   - **dead-man**: stop sending for 35 s, confirm the mode line reports autonomous, then type a key and
     confirm connected mode resumes within one wake;
   - **suspend the ULP** (stop the timer deliberately) and confirm input gets `ERR_NO_ULP` rather than
     disappearing into a ring.
4. Do not bring up flash, paging or the byte server. This probe is the pipe.

## Record

| Item | Value |
| --- | --- |
| attach → first prompt | ms, 10 samples min/median/max |
| 200 paced lines | drops_out, lost input, duplicates (all must be 0) |
| 4 KB unpaced paste | bytes sent / bytes received / reported loss |
| second opener | refusal message, first session unaffected yes/no |
| dead-man → autonomous | within 35 s yes/no |
| resume after idle | within one wake yes/no |
| ULP stopped | `ERR_NO_ULP` shown yes/no |

## Pass criteria

* 200 paced lines with zero losses and no duplicates;
* unpaced paste loses bytes **loudly** (a count is reported) — silent loss is a `FAIL`;
* second opener refused by name, first session untouched;
* dead-man and resume both work;
* stopped ULP produces `ERR_NO_ULP`, never a hang.

## Failure criteria — and what each changes

* **Paced lines still drop** ⇒ the pacing rule is insufficient at this baud; raise the baud or add a
  credit scheme, and restate `06-repl.md` §5.
* **Attach latency > 50 ms** ⇒ the tool must pre-warm (send a mode frame before the prompt is
  expected), or the claim "feels immediate" is wrong and §5 changes.
* **Second opener is not refused** ⇒ the OS-level lock is the only defence and it must be in
  `ulpctl`, not hoped for from the driver.
* **Dead-man does not fire** ⇒ an empty terminal keeps the ULP at 32–64 ticks forever, burning power
  for nothing; the timer moves into the bridge's own task with a hard bound.

## Doc deltas to hand back

* `docs/06-repl.md` §5 (latency and flow control), §6 (session lifecycle) — with the measured table.
* `docs/01-proposal.md` §10 R8 items 1, 2, 3, 6, 7 — restated with measurements.

## Do not

* Do not implement paging, storage or the byte server here; a REPL that cannot show a prompt is not
  testing anything.
* Do not use `/dev/ttyACM0` for the console; that port belongs to `esptool`.
* Do not leave the ULP timer stopped or the bridge task spinning when you finish — restore a known
  state and say what is flashed.
