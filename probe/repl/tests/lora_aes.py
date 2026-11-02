"""lora_aes.py - does the AES-128 block cipher in Forth produce the right block?

The expectation is not remembered: tests/lora_aes_vector.json holds the round
keys computed from the FIPS-197 key schedule (validated against the published
A.1 expansion) and the ciphertext produced by `openssl enc -aes-128-ecb`.
Recalled values were wrong twice while this was written, so nothing here is
typed from memory.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))

from devio import Dev                      # noqa: E402
from lintgate import require_clean         # noqa: E402

REPO = HERE.parent.parent.parent
CIPHER = REPO / "examples/apps/lora/lora_aes.fs"
VECTORS = HERE / "data" / "lora_aes_vectors.fs"
EXPECT = json.load(open(HERE / "data" / "lora_aes_vector.json"))


def load(dev, path):
    """Send a Forth source line by line. Returns the lines the board refused."""
    bad = []
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("\\"):
            continue
        reply = dev.cmd(line, 15.0, allow_error=True)
        last = [s.strip() for s in reply.strip().splitlines() if s.strip()][-1]
        if "ERR" in last:
            bad.append((line, last))
    return bad


def hex_st(dev):
    return "".join(f"{dev.num(f'{o} ST + C@ .', 10.0):02x}" for o in range(16))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    a = ap.parse_args()

    # GUARDRAIL: the linter is a gate, not advice (AGENTS.md). It runs before the port is opened, so a broken source
    # never costs a board round trip.
    require_clean([CIPHER], "--repl", where="aes-cipher")
    require_clean([VECTORS], "--repl", where="aes-vectors", use=[CIPHER])

    fails = 0
    def check(name, ok, detail=""):
        nonlocal fails
        if not ok:
            fails += 1
        print(f"  {'PASS' if ok else 'FAIL'}  {name:42s} {detail}")

    dev = Dev(port=a.port)
    dev.reset()
    h0, l0 = dev.num("HERE ."), dev.num("LATEST .")
    bad = load(dev, CIPHER)
    h1, l1 = dev.num("HERE .", 20.0), dev.num("LATEST .", 20.0)
    size = h1 - h0 + l0 - l1
    check("cipher loads with no refused line", not bad, f"{bad[:1]}")
    check("cipher fits the prompt dictionary", l1 - h1 >= 0, f"{size} B used, {l1-h1} B free")

    # GUARDRAIL: `free 0` plus a definition that does not fit leaves a DANGLING header: the line answers `ok` and the
    # word is not findable afterwards. Measured on this very file with FIN. Ask the board, not the source.
    for w in ("AESB", "ARK", "MC", "SR"):
        r = [s.strip() for s in dev.cmd(f"' {w} .", 10.0, allow_error=True).splitlines() if s.strip()][-1]
        check(f"{w} exists after the load", r.endswith("ok"), r)

    bad = load(dev, VECTORS)
    check("vectors load with no refused line", not bad, f"{bad[:1]}")
    want_pt = "".join(f"{b:02x}" for i in range(4) for b in EXPECT["PT"][i].to_bytes(4, "big"))
    check("plaintext is in ST", hex_st(dev) == want_pt, hex_st(dev))

    dev.cmd("AESB", 60.0, allow_error=True)
    got = hex_st(dev)
    check("AES-128 block matches openssl", got == EXPECT["cthex"], f"{got} want {EXPECT['cthex']}")

    print(f"  {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
