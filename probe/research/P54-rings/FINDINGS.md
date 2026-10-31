# P54 idea 5 — merge the output and command rings: **NO-GO**

**Answer: merging the two rings cannot buy a single byte of `.bss` without losing worst-case buffering, and
the shapes that keep the capacity save exactly 0 B.** The idea is dead by counting, not by tuning:

> The reference state is **64 B of command pending AND 128 B of output pending, at the same instant = 192 B**.
> Any ring that holds that state needs **≥ 192 B of byte storage**. Shipping already stores **192 B**
> (`repl_cmd[64]` + `repl_out[128]`, and they are already adjacent in `.bss`: `repl_out` at `0x1b40`,
> `repl_cmd` at `0x1bc0`). A merge therefore has **no byte to win in the arrays**, and the only shape that
> saves the tempting 64 B is a **128 B** ring, which cannot hold 192 B. Measured: the capacity-preserving
> merge is **Δ.bss = 0, Δ.text = +4** against a like-for-like control; the 64 B-saving merge is
> **Δ.bss = −64, at the cost of 64 B of worst-case output capacity** — forbidden by the operator's condition.

A NO-GO here is the intended result: the arithmetic is the deliverable. Everything below is the arithmetic,
machine-checked where a machine can check it.

---

## 1. Capacity, defined once, with the code that decides it

**Definition.** `cap_cmd` = the largest number of command bytes the design can hold while the output
direction is simultaneously at *its* maximum (`cap_out`), and symmetrically `cap_out`. Worst-case
simultaneous capacity = `cap_cmd + cap_out` at the corner state `(cap_cmd, cap_out)`. This is the operator's
definition and it is the only one that matters here: neither direction may be starved to feed the other.

Today's numbers come from four guards, two on each core:

| direction | limit | where |
|---|---|---|
| command, capacity 64 | the HP refuses to write when full: `if ((h - t) >= CMD_SIZE) break;` — "full: let the ULP catch up, drop nothing" | `../../repl/main/repl_main.c:78` (`CMD_SIZE 64u`, `:47`) |
| command, consumption | the ULP drains ≤ 32 B per wake: `if (n > CMD_BUDGET) n = CMD_BUDGET;` … `repl_cmd[(t + i) & CMD_MASK]` … `repl_cmd_tail = t + n;` | `src/ulp_repl.c:330,333,351` (`CMD_BUDGET 32u`, `:186`) |
| output, capacity 128 | the ULP drops when full: `if ((h - t) >= OUT_SIZE) { repl_out_drop++; return; }` then `repl_out[h & OUT_MASK] = c` | `src/ulp_repl.c:131-136` (`OUT_SIZE 128u`, `:95`) |
| output, consumption | the HP drains ≤ 64 B per console pass, one `msg_drain_ring` call | `../../repl/main/repl_main.c:84-94` |

So **`cap_cmd = 64`, `cap_out = 128`, worst case 192 B**, and `src/ulp_repl.c:94-97` is the whole story:
`CMD_SIZE 64u`, `OUT_SIZE 128u`, and each direction has its own `(head, tail)` pair — four indices, **one
writer each** (`repl_main.c:10-16`): the HP writes `cmd_head`/`out_tail`, the ULP writes `cmd_tail`/`out_head`.

### 1.1 The corner is reachable, in code order, with the real periods

Not a pathological interleaving — the HP does it every pass, because of the order of two loops:

1. `repl_main.c:66-81` first reads up to 64 UART bytes and writes them until the command ring is full;
2. **only then** `repl_main.c:84-94` drains **one** 64 B staging pass of output.

The ULP wakes every **6 460 µs** (`repl_main.c:225`) and drains ≤ 32 command bytes per wake, so the HP's 10 ms
pass (`vTaskDelay(1)` at `CONFIG_FREERTOS_HZ=100`) refills faster than the ULP empties: 64 written vs ~50
drained per pass. On the output side one line can emit far more than 64 B in a **single wake**: `TYPE` emits `n`
bytes straight off the stack in one `while (n--)` loop (`p31_cases.inc:154`), and `."` emits the whole quoted
string in interpret state (`p31_cases.inc:203`), up to the 127-byte line buffer. (The error path is *not* a big
burst: the parsed word is capped at 31 chars — `uforth.c:433` — so `err()` emits ≤ 33 B.) Compose the two: a line
that prints while the next line is typed ahead, and the pass leaves **64 B of command pending and 128 B of
output pending at the same instant**. That state is legal today and `pl_emit` only starts dropping *past* it.
The model in §3 confirms `(64,128)` is reachable; the reference figure is real, not invented.

---

## 2. Method — the twin, and a like-for-like control

`./measure.sh` compiles `src/ulp_repl.c` with the **shipping** ULP compile command and **shipping** link line.
Baseline self-check first, because a delta from an unverified twin is not a measurement:

```
$ ./measure.sh base
base       elf .text=5252  .rodata=308  .data=1416  .bss=877  | obj .text=6106  .rodata=308 | sha=5e9434a7c6096071
$ riscv32-esp-elf-objcopy -O binary --only-section=.text <shipping ulp_main.elf> out/ship.text
$ sha256sum out/ship.text out/base.text
5e9434a7c609607128949f1741f0af0e1ba207ab31a04ef5980da676a3e0a7f1  out/ship.text
5e9434a7c609607128949f1741f0af0e1ba207ab31a04ef5980da676a3e0a7f1  out/base.text
```

The twin **is** the flashed image, byte for byte. No board, no flash, no `idf.py`, `/dev/ttyACM*` untouched.

`src/ulp_repl.c` was **not modified** (`diff -q src/ulp_repl.c ../../repl/src/ulp_repl.c` → identical); the
variants live in `variants/` and are selected with `measure.sh`'s `ULP_SRC=` override (a missing file is fatal,
never silently defaulted; the override is the only edit to `measure.sh`). Each variant is a full copy of the ULP
file so the diff is the whole design.

**Why a control.** Every merged variant has to rewrite the boot assert (`sizeof repl_cmd` no longer exists) and
a cheaper check is worth −6 B — a "win" measured from the wrong baseline. `variants/base_ctl_assert.c` keeps
shipping's arrays and only reshapes that check, so the merge's own cost can be read off. Without it, shape B
would be reported as −2 B of `.text`, which is the assert, not the merge.

---

## 3. Measured shapes

`Δ` is against `base` (shipping). Capacity columns are from `tools/capacity_model.c` (§3.1), not from opinion.

| # | shape | worst-case cmd B | worst-case out B | max simultaneous | Δ.text | Δ.bss | verdict |
|---|---|---|---|---|---|---|---|
| A | **today**: `repl_cmd[64]` + `repl_out[128]`, 4 cursors | **64** | **128** | **192** | — (5 252) | — (877) | reference |
| — | *control*: same arrays, boot assert reshaped | 64 | 128 | 192 | −6 (5 246) | 0 | control only |
| B | one `repl_ring[192]`, hard split 64+128, output at offset 0 | 64 | 128 | 192 | −2 (5 250) | **0** | **NO-GAIN** — capacity identical, saves nothing, needs a host-side pointer change |
| B′ | same but output at offset 64 (the "natural" low-first layout) | 64 | 128 | 192 | −2 (5 250) | **0** | same, and `pl_emit` pays an extra `addi a3,a3,64` (+4 B) |
| C | one `repl_ring[128]`, hard split 64+64 | 64 | **64** | **128** | −2 (5 250) | **−64** (813) | **NO-GO** — output capacity −64 at cmd saturation; 192 > 128 |
| C′ | one `repl_ring[128]`, split 48+80 | 48 | 80 | 128 | — | −64 | **NO-GO** — loses on *both* sides; no split of 128 passes |
| D | one ring, **one** `(head, tail)` pair | — | — | — | — | −64 | **NO-GO, incoherent**: 2 producers + 2 consumers on one cursor pair breaks the one-writer-per-index rule (§5) |
| E | one `repl_ring[192]`, *perfect* dynamic boundary | 192 (borrowed) | 192 (borrowed) | 192 | +? | **0** | **NO-GAIN** — meets the corner with **zero slack**; storage unchanged, so 0 B won, and direction metadata costs more (§4) |
| F | one tagged ring: 192 data + 24 B tag bitmap | 192 | 192 | 216 | +? | **+24** | **NO-GO** — the only shape with real sharing headroom is *bigger* than today |

Note B/B′/C all land on `.text = 5 250`. Against the control that is **+4 B**: one `addi` to reach the second
region's base (`addi a3,a3,64` in `pl_emit` for B′, `addi a5,a5,128` inside the inlined drain for B and C). The
rest of the ±4 B churn between variants is address-layout noise (every store offset in `main` shifts, visible by
diffing the disassembly); it is not ring logic and it is not a win. The one honest byte figure, if B shipped
as-is: `.text` 5 252 → 5 250, `.bss` unchanged → **2 B of app space for coupling two rings in one array**, and
2 B is available *without* the merge by reshaping the assert.

### 3.1 The capacity arithmetic, machine-checked

`tools/capacity_model.c` models the four guard rules (write/drain on each direction, refusals exactly as
`pl_emit` and `repl_main.c:78` implement them) and closes the reachable `(cmd_used, out_used)` set. It cannot
tell you how often the corner happens (that needs a probe); it tells you whether it exists at all.

```
$ gcc -O2 -o artifacts/capacity_model tools/capacity_model.c && ./artifacts/capacity_model
shape                               storage  cmd_max out_max  max_tot  cmd|out=128  out|cmd=64  out|cmd=128  corner(64,128)
A today: 64 + 128 separate             192       64     128      192          64         128            0  REACHABLE
B one 192 array, split 64+128          192       64     128      192          64         128            0  REACHABLE
C one 128 array, split 64+64           128       64      64      128           0          64            0  no
C' one 128 array, split 48+80          128       48      80      128           0           0            0  no
E one 192 array, perfect dynamic       192      192     192      192          64         128           64  REACHABLE
E' one 128 array, perfect dynamic      128      128     128      128           0          64            0  no
F one tagged 192 (192 + 24 B tags)     216      192     192      216          88         152           88  REACHABLE
G 192 shared pool, caps kept 64/128    192       64     128      192          64         128            0  REACHABLE

ok     today reaches (64 in, 128 out): 192 B at once, both full
ok     shape B (192 hard split) reaches the SAME corner — the checker is not a rubber stamp
ok     shape C loses 64 B of output at cmd=64 (128 -> 64)
ok     no 128 B split passes: C' loses input (64 -> 48) and output (128 -> 80)
ok     perfect dynamic 192 meets the corner with ZERO slack (max_total == storage == 192)
ok     perfect dynamic 128 CANNOT meet it: 64 + 128 = 192 > 128
ok     tagged 192 costs 24 B MORE storage than today for the same 192 B of capacity
ok     capacity-safe dynamic 192 (shape G) reaches EXACTLY today's pair set, pair for pair
ok     and its input headroom at output saturation is still 64 — the merge buys 0 B of capacity
ok     dynamic 192 with input past 64: output headroom at its own input cap is 64, today's is 128
ok     ... because 128 + 128 = 256 > 192: the second 64 B of reply has nowhere to go
ok     MUTATION: 128 B storage with 192/192 caps still cannot reach (64,128)
ok     MUTATION: a 128 B array with uncoupled 64+128 guards FALSELY passes (proves `coupled` matters)
model ok: the capacity arithmetic holds
```

`tools/caps_agree.sh` ties the model's inputs to the two cores' sources and fails loud on drift:

```
$ ./tools/caps_agree.sh
ulp_repl.c     CMD_SIZE=64  OUT_SIZE=128
repl_main.c    CMD_SIZE=64  OUT_SIZE=128
capacity_model A today: 64 + 128 separate             192       64     128      192          64         128            0  REACHABLE
ok    model, ULP and host describe one ring pair: 64 + 128 B, 192 B simultaneous
```

**Mutation tests** (break it, watch it fail, restore — all three restored and re-run green):
1. inside the model: a "128 B storage with 192/192 caps" lie must not reach the corner → it does not;
2. inside the model: a 128 B array with *uncoupled* 64+128 guards must (falsely) pass → it does, which is what
   makes the `coupled` flag load-bearing rather than decorative;
3. outside the model: editing row A to a fictional 64+64 design makes four checks fail (`MODEL FAILED`, exit 1);
4. `caps_agree.sh` must not pass on a model that describes a different ring pair: with the model claiming
   96+128 it prints `FAIL capacity_model's 'today' row is not the 64 + 128 design` and exits 1.

---

## 4. Why nothing wins: the dilemma, stated as arithmetic

- **Storage lower bound.** 64 + 128 = 192 bytes must be storable simultaneously ⇒ any capacity-preserving
  ring is ≥ 192 B ⇒ merging two 192 B-total arrays into one 192 B array saves **0 B**. This is shape B, and it
  is measured: `.bss` 877 → 877.
- **Every 128 B split fails.** To keep the reference you need `cmd ≥ 64` **and** `out ≥ 128` in a 128 B array:
  `64 + 128 = 192 > 128`. Try to be fair (48/80): still fails, on both sides. Shape C's −64 B is bought
  *precisely* with the 64 B of output capacity the operator forbade; there is no third option inside 128 B.
- **Dynamic sharing on a 192 B budget is a no-op.** Row G proves the pair set is *exactly* today's, pair for
  pair: since `64 + 128 = 192` is the whole pool, the sharing constraint `cmd + out ≤ 192` is **implied** by the
  caps. Sharing can only add headroom if it removes some, and the corner already uses all of it. So the shape
  that is capacity-safe is worth 0 B, and it is not free: a dynamic boundary must either
  (a) carry a **direction bit per byte** — 192 bits = 24 B of `.bss`, so 216 B > 192 B (row F, strictly worse
  than shipping), or
  (b) move the boundary, which means moving a sub-ring's base, which means moving **the other side's cursor** —
  a second writer on an index, i.e. exactly the P27 traffic rule and the F-107 replay bug that
  `ulp_repl.c:101-104` records ("the host wrote past the end of `repl_cmd[]` into `repl_out[]` and the REPL
  replayed stale characters (`3 CUBE .H`, `.HERE?`)").
- **And the sharing direction that a user would actually want loses.** Let the shared ring honour a paste
  (TIBSZ is 128, so 128 command bytes can be pending). Now 128 typed + 128 reply = **256 > 192**, so output
  headroom at the input cap falls to **64** where today it is **128** (model rows `out|cmd=128`, and the
  `dyn 192, input uncapped` check). One documented lost case, therefore NO-GO — and if you instead *cap* input
  at 64 to protect the output, you are back to row G, which is today, worth 0 B.

---

## 5. The "one ring, one head/tail" temptation is not merely lossy — it is incoherent

The version of this idea that looks free — "one ring, one `head`, one `tail`, 64 B of `.bss` saved" — cannot
be built at all, whatever its capacity. In one cursor pair there is exactly one producer position and one
consumer position. The command direction needs: producer **HP**, consumer **ULP**. The output direction needs:
producer **ULP**, consumer **HP**. One pair therefore asks two cores to be producer and two to be consumer at the
same addresses: the HP's output reader would walk the ring from the tail and consume **its own typed bytes** as
if they were output, and the ULP's drain would read whatever the HP had already advanced past. `pl_emit`'s
stream and the echo would interleave into one FIFO whose direction is unknowable per byte (most output bytes are
ASCII < 0x80, exactly like typed input — `msg_codes.h:9-13` relies on that for codes, and it is what makes
tag-free disambiguation impossible).

The two directions are only separable with **four cursors, one writer each** (`repl_main.c:10-16`). Four cursors
mean two regions. Two regions in one array is shape B (0 B saved). This is why the idea has no escape route.

---

## 6. The drop-count question: which bytes, and how many more

`pl_emit` (`src/ulp_repl.c:127-137`) drops the **newest** byte: on a full ring it increments `repl_out_drop` and
returns **without** writing and **without** advancing `head`. So a truncated reply loses its **tail** — the end
of the line, including the `'\n'` and any message code — and nothing on the wire marks it. That is exactly why
`ulp_repl.c:91-93` insists the counter stays reachable.

For a burst of `B` bytes emitted while `p` are pending, dropped bytes are `max(0, p + B − SIZE)`:

- **today** (`SIZE = 128`): `max(0, p + B − 128)`;
- **shape C** (`SIZE = 64`): `max(0, p + B − 64)`.

So `Δdrops = min(64, max(0, p + B − 64))`: **64 more** for every burst that today's ring would fill
(`p + B ≥ 128`), a partial 0…64 for middling bursts, and 0 only below 64 B. A single line is enough to trigger
it: `TYPE` emits an unbounded count from the stack (`p31_cases.inc:154`), so a `p + B ≥ 128` burst needs no
special timing; shape C then drops **64 more bytes than today** in that state and truncates the operator's
output mid-line. The absorbing ability per HP pass *is* the ring size, so halving the ring halves what a burst
can survive: C's worst case is 64 B absorbed per 10 ms pass against today's 128 B.

- **Shape B** drops byte-for-byte the same stream as today (identical `OUT_SIZE`, identical emit order, only the
  array base differs) — no count change, which is the one thing it gets right.
- **Shape C** adds `min(64, …)` drops per saturated burst, counted but invisible to the operator.
- **Shape E/F** (dynamic) can drop *fewer* output bytes but converts a new failure class into existence: the
  HP's command writer must now be refused or stalled when the shared pool is full of unread **output**, so
  typed input can be dropped or head-of-line blocked by output. Today that is impossible by construction —
  `repl_main.c:78` **never drops**: it breaks out and lets the UART path retry. A merged ring turns "input is
  never lost" into "input is lost when output is busy". That is not measurable on the host (§7) and it is
  another reason a shared pool is not worth 0 B.

---

## 7. What I could not measure

- **The HP half of any merged design.** Shapes B/B′/C rename `ulp_repl_cmd`/`ulp_repl_out` to one
  `ulp_repl_ring`, so `main/repl_main.c` must take its output pointer as `base + offset` (and its boot assert at
  `repl_main.c:217` must change with it). That is a second build tree; only the ULP `.text`/`.bss` are priced
  here. The HP cost is *unmeasured* — it cannot be quoted as zero.
- **`.bss` → app space.** 64 B of `.bss` is worth ~64 B of app space by the brief's currency, but only after a
  re-bake at a raised `MEMSZ` (`tools/bake.sh`, which owns that). Not done: there is no GO to bake for, and a
  re-bake moves the image (`E-079`).
- **Board behaviour of a merged ring**: drop counts under real paste timing, and the input-loss class in §6,
  need a probe on `/dev/ttyACM*` — forbidden here. The capacity argument does not need it (capacity is a
  counting property, not a timing one), but "how often the corner is hit" is a probe question, still open.
- **The ULP ring code is not exercised by `tests/run.sh`.** That suite builds `src/uforth.c` with `-DHOST`
  (where `pl_emit` is `putchar`, `uforth.c:946`) and drives the **host-side** `msg_drain_ring`
  (`src/msg_expand.h`) in `tools/ring_test.c`. So no host test can regress-detect a ULP ring change; that is
  why §3.1 is a guard model tied to the sources rather than a claim about the firmware. Run anyway, on the
  untouched `src/`: **all green** (`PASS addr/blocks/blocks_noserver/deep/lookup/ntsk/semantics/suite`,
  `PASS ring drain`, `PASS unknown message code is named`) — a control showing the twin's source is the suite's
  source.

---

## 8. Reproduce

```
./measure.sh base                                  # must print sha=5e9434a7c6096071 (== shipped .text)
ULP_SRC=variants/base_ctl_assert.c ./measure.sh base_ctl_assert   # 5246 / 877 — the control
ULP_SRC=variants/ring_merged192.c  ./measure.sh ring_merged192    # 5250 / 877
ULP_SRC=variants/ring_merged192b.c ./measure.sh ring_merged192b   # 5250 / 877
ULP_SRC=variants/ring_split128.c   ./measure.sh ring_split128     # 5250 / 813  <-- the 64 B, priced
gcc -O2 -Wall -Wextra -o artifacts/capacity_model tools/capacity_model.c && ./artifacts/capacity_model
./tools/caps_agree.sh
./tests/run.sh
```

The exact change of the only shape that saves bytes (shape C) — from `variants/ring_split128.c`; the rest of
that file is `src/ulp_repl.c` with `repl_cmd[..]`/`repl_out[..]` rewritten as `repl_ring[OFF + ..]`:

```diff
 #define CMD_SIZE 64u
-#define OUT_SIZE 128u
+#define OUT_SIZE 64u                 /* was 128: THIS is the 64 B capacity loss, in one line */
 #define CMD_MASK (CMD_SIZE - 1u)
 #define OUT_MASK (OUT_SIZE - 1u)
+#define CMD_OFF  0u
+#define OUT_OFF  CMD_SIZE            /* 64; both regions are power-of-2 sized, so no wrap arithmetic */
+#define RING_BYTES (CMD_SIZE + OUT_SIZE)
 ...
-volatile u8  repl_cmd[CMD_SIZE];
-volatile u8  repl_out[OUT_SIZE];
+volatile u8  repl_ring[RING_BYTES];
 ...
-    repl_out[h & OUT_MASK] = (u8)(c & 0xff);
+    repl_ring[OUT_OFF + (h & OUT_MASK)] = (u8)(c & 0xff);
 ...
-        u8 c = repl_cmd[(t + i) & CMD_MASK];
+        u8 c = repl_ring[CMD_OFF + ((t + i) & CMD_MASK)];
 ...
-        if (repl_cmd_bytes != (u32)sizeof repl_cmd || repl_out_bytes != (u32)sizeof repl_out)
+        if (repl_cmd_bytes + repl_out_bytes != (u32)sizeof repl_ring)
             pl_halt(0x60);
```

---

## 9. Recommendation

**Do not merge the rings. Drop idea 5.** The `.bss` is not there: 192 B of buffering needs 192 B of storage, the
two regions already sit in one contiguous 192 B block, and the four cursors cannot be reduced without breaking
the one-writer-per-index rule that keeps the console lock-free — so the merge's maximum possible win is **0 B**
and its realistic price is a host-side pointer change plus one more way to drop a reply.

If 64 B of app space is genuinely wanted, it has to come from somewhere that is not worst-case capacity. One
lead, not measured here and outside this task's scope — recorded so it is not re-derived as "the ring merge
would have done it":

- **Cursor width, not ring layout.** The four cursors are `volatile u32` (16 B). With `u8` free-running indices
  the occupancy test `h - t` still works mod 256 for ring sizes that divide 256 (64 and 128 both do), so the
  rings keep their *full* capacity and ~12 B of `.bss` is freed. It is a cross-core ABI change (`repl_main.c`
  uses `uint32_t`) and must be measured, not assumed — the two cores must agree or the boot assert fires.

What is *not* a lead: moving the rings into `mem[]`. `static u8 mem[MEMSZ]` is `.bss` too, so a move is an
accounting shuffle of the same pool, not a saving — and it would put the rings inside the block window's
neighbourhood for no gain.
