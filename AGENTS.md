# Agent notes — esp32-rv32

Probe rules, each paid for with a specific failure: **[docs/14-probe-rules.md](docs/14-probe-rules.md)** — read it before running a probe.

**Every Forth source goes through the linter before it runs or is committed:** `python3 probe/repl/tools/lint_forth.py --repl <file.fs>` for anything typed at the prompt, `--phase <file.fs>` for block-uploaded phases (or `probe/repl/tools/lintgate.py`, which wraps both and refuses on ANY finding). A refusal is a build error, not advice.
