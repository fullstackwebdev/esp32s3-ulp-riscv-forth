#!/usr/bin/env python3
"""Does the stock node's radio even SEE our transmission? Count its own preamble/header/decrypt events.

    python3 tests/mesh_preamble_probe.py --peer /dev/ttyUSB1 --ours /dev/ttyUSB0 --sync 2b --frames 40
    python3 tests/mesh_preamble_probe.py ... --frames 0          # quiet baseline: MUST be 0 events

Why this exists: the peer answers nothing, and silence has three possible causes that need three different fixes -
its radio never correlates our preamble (TX quality), it correlates the preamble but not the sync word (the
undocumented 0x0741 byte), or it gets past both and drops us in software (channel/crypto). Meshtastic's own firmware
log distinguishes them, but only if the counts are read against a quiet baseline.

GUARDRAIL: the firmware DISCARDS preamble/header-only IRQs on purpose (RadioLibInterface sets noisyRxMask and returns
early), so these log lines are a LOWER BOUND and appear late (after 2x preamble time). Compare pairs against each other
and against the baseline - never against the number of frames sent.

GUARDRAIL: a listener and `--sendtext` cannot share the port. Any test that needs the peer to TRANSMIT must not have a
listener attached; that mistake made an earlier "no decode" result meaningless.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
from devio import Dev                      # noqa: E402
from lora_frame_phase import load          # noqa: E402

TXT = {
    "2b": REPO / "examples/apps/lora/loratx_ms_44clamp.fs",     # 0x2B,0x44 - what RadioLib writes
    "2b24": REPO / "examples/apps/lora/loratx_ms_24clamp.fs",   # 0x2B,0x24 - the pair our receiver needed
}
CLR = "NSSLO 2 >BYTE 255 >BYTE 255 >BYTE NSSHI"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--peer", default="/dev/ttyUSB1")
    ap.add_argument("--ours", default="/dev/ttyUSB0")
    ap.add_argument("--sync", choices=sorted(TXT), default="2b")
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--settle", type=float, default=20.0)
    ap.add_argument("--gap", type=float, default=1.5)
    a = ap.parse_args()

    listener = subprocess.Popen(["meshtastic", "--port", a.peer, "--listen", "--debug"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(a.settle)
    sent = 0
    if a.frames:
        dev = Dev(port=a.ours)
        dev.reset()
        load(dev, TXT[a.sync])
        init = dev.num("RADIO-INIT .", 40.0)
        if init != 1:
            listener.kill()
            raise SystemExit(f"our board refused to configure (RADIO-INIT={init})")
        for _ in range(a.frames):
            dev.cmd(CLR, 10.0, allow_error=True)
            dev.num("GO .", 60.0)
            sent += 1
            time.sleep(a.gap)
        dev.close()
    time.sleep(10)
    listener.kill()
    log = listener.communicate()[0] or ""
    out = REPO / "probe/results" / f"preamble_{a.sync}_{a.frames}.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(log)

    counts = {
        "sent": sent,
        "preamble_events": log.count("Ignore false preamble detection"),
        "header_events": log.count("Ignore false header detection"),
        "decrypt_attempts": len(re.findall(r"Use AES\d+ key", log)),
        "no_suitable_channel": log.count("No suitable channel"),
        "our_packet_decoded": log.count("hi from ulp"),
        "crc_or_header_errs": len(re.findall(r"(CRC_ERR|HEADER_ERR|CrcErr|HeaderErr)", log)),
    }
    print(json.dumps(counts))
    pathlib.Path(str(out).replace(".log", ".json")).write_text(json.dumps(counts, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
