# Probe results

One directory per probe: `P<NN>-<slug>/`, containing

```
RESULT.md          answers, evidence, verdict, doc deltas, follow-ups
*.log              complete command output (never tail-ed)
*.c / *.fs / *.py  any code the probe wrote (copies, not edits of the baseline)
```

Rules:

* **Never edit `docs/` from inside a probe.** The orchestrator applies doc deltas.
* **Never edit `probe/uforth/uforth.c`** — it is the baseline the review in
  `docs/03-prototype-review.md` refers to. Copy it if you need to change it.
* **A probe that cannot run prints `BLOCKED: <reason>`** and stops. No fallbacks, no skipped cases.
* **Board probes are exclusive** — one at a time, and only with explicit approval, because flashing
  overwrites the firmware.
* Timeouts are mandatory in any test runner: a Forth VM with a bad branch operand hangs, and that has
  already happened once here.

Nothing here exists yet. The first three to run are `P01` (engine size), `P02` (token width) and
`P05` (clock), because they can falsify the resident budget and the timing model before any larger
build.
