#!/usr/bin/env bash
# verify.sh — one command, all the numbers for FINDINGS.md.
#
#   1. twin-build src_base (pristine) and src (one-byte codes) and print the section sizes + delta
#   2. prove all 8 messages in src/msg_codes.h are byte-for-byte what the SHIPPING image carries
#   3. prove the operator transcript is byte-identical (file suite, interactive, task-table refusal)
#   4. prove the ring drain loses nothing when the staging buffer fills up mid-message
#   5. print the blocks countdown both ways (the project's own unit)
set -euo pipefail
cd "$(dirname "$0")/.."
SHIP=../../repl/build/esp-idf/main/ulp_main/ulp_main.elf

echo "== 1. ULP section sizes (twin build, same compiler/flags/link line) =="
nice -n 15 timeout 600 ./measure.sh src_base base  | tee out/size_base.txt
nice -n 15 timeout 600 ./measure.sh src coded      | tee out/size_coded.txt

echo
echo "== 2. every message in msg_codes.h is the shipping image's own text =="
python3 tools/check_strings.py "$SHIP"

echo
echo "== 3. transcript identity (host engine, both trees) =="
nice -n 15 timeout 600 ./tools/transcript.sh

echo
echo "== 4. ring drain, including the buffer-full retry =="
gcc -O2 -Wall -Wextra -o out/ring_test tools/ring_test.c
./out/ring_test

echo
echo "== 5. blocks countdown, project units (countdown.sh arithmetic, TEXT+RODATA+BSS) =="
python3 - out/size_base.txt out/size_coded.txt <<'PY'
import re, struct, sys

def sizes(path):
    # GUARDRAIL: parse tokens, not a `data=(\\d+)` regex — "rodata=372" contains "data=372", so a
    # substring search reported .data as 372 B and invented a 248 B image delta instead of 144 B.
    kv = dict(tok.split("=") for tok in open(path).read().split() if "=" in tok)
    return int(kv["text"]), int(kv["rodata"]), int(kv["data"]), int(kv["bss"])

bt, br, bd, bb = sizes(sys.argv[1])
ct, cr, cd, cb = sizes(sys.argv[2])
img_h = open("src/image.h").read()
raw = re.findall(r"0x([0-9a-f]{2})", img_h)
b = bytes(int(x, 16) for x in raw)
vhere, vlatest = struct.unpack_from("<II", b, 4)[0], struct.unpack_from("<II", b, 8)[0]
MEMSZ = int(re.search(r"#define MEMSZ\s+(\d+)", open("src/ulp_repl.c").read()).group(1))
POOL, BLK_DICT, BLKSZ, BLK_CODE, DATA_PAD = 7856, 40, 512, 810, 16
APP = vlatest - vhere
NEED = BLK_DICT + BLKSZ + BLK_CODE
print(f"{'':7s} {'text':>5s} {'rodata':>6s} {'data':>5s} {'bss':>5s} {'image':>6s} {'have':>5s} {'gap':>5s}")
for tag, (t, r, d, bs) in (("before", (bt, br, bd, bb)), ("after", (ct, cr, cd, cb))):
    overhead = t + r + bs
    pool_used = overhead + MEMSZ + DATA_PAD
    have = APP + POOL - pool_used
    print(f"{tag:7s} {t:5d} {r:6d} {d:5d} {bs:5d} {t+r+d:6d} {have:5d} {NEED-have:5d}"
          f"   [pool {pool_used}/{POOL}, app {APP}, MEMSZ {MEMSZ}]")
print(f"delta  text {ct-bt:+d}  rodata {cr-br:+d}  ULP image {(ct+cr+cd)-(bt+br+bd):+d} B  "
      f"countdown {-(ct+cr+cd-bt-br-bd):+d} B of block budget")
PY
