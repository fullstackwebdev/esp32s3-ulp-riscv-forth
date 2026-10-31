# Cache

One store, one fetch per URL, append-only.

```
cache/
  objects/<key>/v0001.bin          raw bytes, write-once (O_EXCL)
  objects/<key>/v0001.meta.json    url, sha256, bytes, http status, content-type, origin
  journal.jsonl                    append-only: every store / hit / miss / refusal
  derived/<key>.txt                derived text (regenerable, never a source of truth)
```

`key = sha256(normalised URL)[:32]`. Normalisation lowercases the scheme/host, drops the fragment,
sorts query parameters and strips per-visit noise (`utm_*`, `sid`, `sessionid`, `fbclid`, …). The key
depends on the URL and nothing else — no caller-chosen filenames, because two names for one URL
means two fetches and a useless cache.

## Use

```sh
python3 tools/fetch.py get URL                # fetch once, then always served from cache
python3 tools/fetch.py get URL --refresh      # append v0002, v0001 is kept
python3 tools/fetch.py get URL --offline      # exit 2 with a named reason on a miss
python3 tools/fetch.py adopt URL ./local.html # register bytes already on disk, no network
python3 tools/fetch.py list                   # what is in here
python3 tools/fetch.py path URL               # print the current version's path
```

Rules the module enforces, because we have been bitten by each of them:

* a miss while offline is **fatal and named** — it never falls back to the network;
* an existing version is **never overwritten** — a refresh appends, history is evidence;
* every stored byte is hashed and journaled with its origin URL;
* an HTTP failure writes **nothing** (no zero-byte or partial objects).

## Contents

| Key | URL | Size | Fetched |
| --- | --- | --- | --- |
| `2bb0d59988d50b29ecd39e86fd19a164` | `https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32s3/api-reference/system/ulp-risc-v.html` | 118 509 B | 2026-10-30T18:59:09Z |
