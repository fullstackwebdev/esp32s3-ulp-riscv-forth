# Sharing this repo

Everything needed to publish the research without shipping anything that should not be public.

## What is published

* All source: the ULP Forth engine (`probe/repl/src`), the bridge (`probe/repl/main`), the host tools, the tests.
* All documentation: `docs/` (index at [`docs/00-index.md`](00-index.md)), including the measured wire facts
  (`31-meshtastic-fit.md`) and the interop handoff (`32-handoff-meshtastic-interop.md`).
* All probe evidence that is text or small binary: captured frame JSON, IRQ words, device logs, `RESULT.md` files.
* The Forth applications in `examples/apps/`, including the LoRa tables and `sync.conf`.

## What is deliberately not published, and why

| excluded | reason |
| --- | --- |
| `backup/*8MB*.bin`, `probe/results/reverify.bin` | full flash dumps include the NVS partition, which holds the node's X25519 keypair. Publishing a dump publishes that device's private key. The `.sha256` and `.identity.txt` files beside them stay, so the evidence trail is intact without the keys. |
| `backup/firmware-2.7.26/*.bin` | Meshtastic firmware images are GPL-3.0. The repo keeps the **recipe and checksums** (`backup/README.md`) and points at the upstream release instead of redistributing binaries. |
| `probe/results/ms-src/` | the cached Meshtastic source tree (1905 files, 24 MB) is third-party code; it is fetched on demand, not vendored. |
| `probe/results/scons45*` | a local build-environment workaround, regenerable, not research. |
| build trees (`build*/`), `*.log` | regenerable; already ignored. |

These exclusions are git-index changes only — the files are still on this machine, untouched. `.gitignore` carries a
`GUARDRAIL` comment on each entry so the reason travels with the rule.

## Fetching the references the docs cite

The docs quote line numbers from Meshtastic's source. Reproduce that tree with:

```sh
# Meshtastic firmware 2.7.26 (the version flashed on the peer node in docs/31 and docs/32)
curl -L https://github.com/meshtastic/firmware/archive/refs/tags/v2.7.26.tar.gz -o ms.tar.gz
mkdir -p probe/results/ms-src && tar -xzf ms.tar.gz -C probe/results/ms-src --strip-components=1
```

If the exact tag is unavailable, `docs/31-meshtastic-fit.md` Appendix N records every constant we took from it
(carrier formula, receive duty cycle, log strings, `variant.h` pin map), so the findings stand on measurements even
without the tree.

## Publishing to GitHub

`gh` is authenticated on this machine as `fullstackwebdev`. From the repo root:

The repository is **`fullstackwebdev/esp32s3-ulp-riscv-forth`** (created private; the old `esp32-rv32` URL redirects).
To publish a change:

```sh
# 1. bring main up to date, non-destructively
git checkout main && git merge --no-ff ulp-meshtastic -m "merge ulp-meshtastic"
git checkout ulp-meshtastic

# 2. push both branches
git push origin main ulp-meshtastic
```

Recreating the remote, if it ever has to be recreated, is a separate step from making it public:

```sh
gh repo create esp32s3-ulp-riscv-forth --private --source=. --remote=origin \
   --description "Forth on the ESP32-S3 ULP-RISC-V coprocessor (RV32IMC, 8 KB RTC RAM)"
```

Choose `--private` instead of `--public` if the write-up should stay closed for now; nothing in the tree assumes
either.

## Before the first push, verify

```sh
git status --short                  # must be empty
du -sh .git                         # history size, not working tree
git ls-files | wc -l                # file count a visitor will see
git ls-files -z | xargs -0 du -h | sort -rh | head -10   # no surprises in the largest files
```

At the time of writing: no secrets in the tracked text (scanned for token/private-key patterns), the largest tracked
files are the retained probe images and documentation assets, and the vendored Meshtastic tree and raw dumps are out
of the index.

## What a reader should take away

The honest headline is in `README.md` and `docs/32-handoff-meshtastic-interop.md`:

* an 8 KB Forth machine on a coprocessor, with a real REPL, multi-tasking, blocks and a store — measured, on hardware;
* a LoRa stack and AES-128-CTR on that coprocessor, whose frames are byte-identical to Meshtastic's own encoding and
  whose receiver decodes a stock node;
* one unsolved direction, stated as unsolved, with the complete experiment log that got there.
