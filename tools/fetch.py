#!/usr/bin/env python3
"""fetch.py — the one and only network read path for this repo.

Everything we pull from the network is stored write-once under
``cache/objects/<key>/vNNNN.bin`` and journaled in ``cache/journal.jsonl``.
The cache only ever grows; a refresh appends a new version and keeps every
earlier one. The key is the *normalised URL*, so two spellings of one URL can
never cost two fetches.

Usage
    fetch.py get URL [--refresh] [--offline]
    fetch.py adopt URL PATH        # register bytes we already have, no network
    fetch.py list [URL]
    fetch.py path URL

Exit codes
    0  ok (cached or fetched)
    2  cache miss while offline  (named reason, no network attempt)
    3  network/HTTP failure      (named reason, nothing written)

// GUARDRAIL: cache keys must be derived from the URL, never from a caller-chosen
// filename — two names for one URL silently means two fetches and an empty cache.
// GUARDRAIL: a cache miss in offline mode must exit non-zero with a named reason —
// falling back to the network makes "offline" a lie and hides gaps in the record.
// GUARDRAIL: never overwrite a cached artefact — old bytes are evidence; a refresh
// writes v(N+1) alongside vN rather than replacing it.
"""
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
OBJECTS = os.path.join(CACHE, "objects")
JOURNAL = os.path.join(CACHE, "journal.jsonl")

# Per-visit noise: never part of a cache key.
NOISE_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "sid", "sessionid", "session_id", "phpsessid", "jsessionid", "_ga", "ref",
    "spm", "from", "share_token", "fbclid", "gclid",
}
USER_AGENT = "esp32-rv32-research/1.0 (+reference cache; one fetch per URL)"


def normalise(url: str) -> str:
    """Canonical form used as the cache key. Deterministic, reversible enough to debug."""
    p = urllib.parse.urlsplit(url.strip())
    scheme = p.scheme.lower() or "https"
    host = p.hostname.lower() if p.hostname else ""
    port = p.port
    netloc = host if port in (None, 443, 80) else "%s:%d" % (host, port)
    path = urllib.parse.quote(urllib.parse.unquote(p.path or "/"), safe="/:@!$&'()*+,;=~")
    query = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
        if k.lower() not in NOISE_PARAMS
    ]
    query.sort()
    return urllib.parse.urlunsplit((scheme, netloc, path, urllib.parse.urlencode(query), ""))


def key_of(url: str) -> str:
    return hashlib.sha256(normalise(url).encode("utf-8")).hexdigest()[:32]


def journal(record: dict) -> None:
    record = dict(record, ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    os.makedirs(CACHE, exist_ok=True)
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def versions(key: str) -> list:
    d = os.path.join(OBJECTS, key)
    if not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d) if n.startswith("v") and n.endswith(".bin"))


def meta_path(key: str, name: str) -> str:
    return os.path.join(OBJECTS, key, name.replace(".bin", ".meta.json"))


def store(key: str, data: bytes, origin: str, extra: dict) -> str:
    """Write-once. Returns the path of the newly written version."""
    d = os.path.join(OBJECTS, key)
    os.makedirs(d, exist_ok=True)
    n = len(versions(key)) + 1
    name = "v%04d.bin" % n
    path = os.path.join(d, name)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL  # GUARDRAIL: O_EXCL — never clobber an existing version
    fd = os.open(path, flags, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    digest = hashlib.sha256(data).hexdigest()
    with open(meta_path(key, name), "w", encoding="utf-8") as f:
        json.dump(dict(extra, sha256=digest, bytes=len(data), origin=origin, version=n), f, indent=1, sort_keys=True)
    journal(dict(extra, event="store", key=key, path=os.path.relpath(path, ROOT),
                 sha256=digest, bytes=len(data), origin=origin, version=n))
    return path


def cmd_get(url: str, refresh: bool, offline: bool) -> int:
    norm = normalise(url)
    key = key_of(url)
    have = versions(key)
    if have and not refresh:
        path = os.path.join(OBJECTS, key, have[-1])
        journal(dict(event="hit", key=key, url=norm, path=os.path.relpath(path, ROOT),
                     sha256=hashlib.sha256(open(path, "rb").read()).hexdigest()))
        print(path)
        return 0
    if offline:
        # GUARDRAIL: named refusal, no silent fetch — this is the whole point of offline mode.
        print("CACHE MISS (offline): %s" % norm, file=sys.stderr)
        print("  key: %s  objects: %d" % (key, len(have)), file=sys.stderr)
        return 2
    req = urllib.request.Request(norm, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
            status = r.status
            ctype = r.headers.get("Content-Type", "")
            final = r.geturl()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        # GUARDRAIL: fail with the URL and the reason; never write a partial/empty object.
        print("FETCH FAILED: %s" % norm, file=sys.stderr)
        print("  reason: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 3
    if not data:
        print("FETCH FAILED: %s — empty body, nothing written" % norm, file=sys.stderr)
        return 3
    path = store(key, data, "http", dict(url=norm, http_status=status, content_type=ctype,
                                         final_url=normalise(final) if final else norm))
    print(path)
    return 0


def cmd_adopt(url: str, src: str) -> int:
    """Register bytes already on disk. No network, ever."""
    norm = normalise(url)
    key = key_of(url)
    with open(src, "rb") as f:
        data = f.read()
    digest = hashlib.sha256(data).hexdigest()
    for name in versions(key):
        if hashlib.sha256(open(os.path.join(OBJECTS, key, name), "rb").read()).hexdigest() == digest:
            journal(dict(event="already-present", key=key, url=norm, sha256=digest, src=src))
            print(os.path.join(OBJECTS, key, name))
            return 0
    path = store(key, data, "adopt:" + src, dict(url=norm, http_status=None, content_type=""))
    print(path)
    return 0


def cmd_list(url: str) -> int:
    keys = [key_of(url)] if url else sorted(os.listdir(OBJECTS)) if os.path.isdir(OBJECTS) else []
    if not keys:
        print("cache is empty")
        return 0
    for key in keys:
        for name in versions(key):
            p = os.path.join(OBJECTS, key, name)
            st = os.stat(p)
            try:
                m = json.load(open(meta_path(key, name)))
                u = m.get("url", "?")
            except (OSError, ValueError):
                u = "?"
            print("%s  %8d  %s  %s" % (key, st.st_size, name, u))
    return 0


def cmd_path(url: str) -> int:
    have = versions(key_of(url))
    if not have:
        print("CACHE MISS: %s" % normalise(url), file=sys.stderr)
        return 2
    print(os.path.join(OBJECTS, key_of(url), have[-1]))
    return 0


def main(argv: list) -> int:
    if len(argv) < 3:
        print(__doc__.strip().splitlines()[0])
        print("usage: fetch.py get URL [--refresh] [--offline] | adopt URL PATH | list [URL] | path URL",
              file=sys.stderr)
        return 1
    cmd, url = argv[1], argv[2]
    rest = argv[3:]
    if cmd == "get":
        return cmd_get(url, "--refresh" in rest, "--offline" in rest)
    if cmd == "adopt":
        if len(rest) != 1:
            print("adopt needs exactly one file path", file=sys.stderr)
            return 1
        return cmd_adopt(url, rest[0])
    if cmd == "list":
        return cmd_list(url if url != "-" else "")
    if cmd == "path":
        return cmd_path(url)
    print("unknown command: %s" % cmd, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
