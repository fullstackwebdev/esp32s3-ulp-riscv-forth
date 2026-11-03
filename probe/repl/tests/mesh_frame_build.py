#!/usr/bin/env python3
"""Build the exact frame the peer expects: 16 B clear header + AES-128-CTR(Data) ciphertext.

    python3 tests/mesh_frame_build.py [--from 0x02AAAAAA] [--id 0x2C3B4A1D] [--text "hi from ulp"] [--portnum 1]

Everything here was MEASURED from a real packet captured off the air (probe/results/captured_peer_frame.txt):
  * the channel byte is xorHash("LongFast") ^ xorHash(psk) = 0x08, even though the node's stored channel name is empty -
    the firmware fills the name from the preset at runtime, so deriving the hash from the stored name gives 0x02 and the
    peer silently drops the packet as "channel not found";
  * the ciphertext covers the Data message (portnum + payload), NOT a MeshPacket wrapper;
  * the nonce is packetId u64 LE || from u32 LE || 4 zero bytes, AES-128-CTR with the channel PSK.
"""
import argparse
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE / "data/mesh_packet.json"
DEFAULT_PSK = "d4f1bb3a20290759f0bcffabcf4e6901"


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default="0x02AAAAAA")
    ap.add_argument("--to", default="0xFFFFFFFF")
    ap.add_argument("--id", default="0x2C3B4A1D")
    ap.add_argument("--text", default="hi from ulp")
    ap.add_argument("--portnum", type=int, default=1)          # TEXT_MESSAGE_APP
    ap.add_argument("--hop-limit", type=int, default=3)
    a = ap.parse_args()
    frm, to, pid = int(a.frm, 0), int(a.to, 0), int(a.id, 0)
    data = bytes([0x08]) + varint(a.portnum) + bytes([0x12]) + varint(len(a.text.encode())) + a.text.encode()
    nonce = pid.to_bytes(8, "little") + frm.to_bytes(4, "little") + bytes(4)
    psk = bytes.fromhex(DEFAULT_PSK)
    ct = subprocess.run(["openssl", "enc", "-aes-128-ctr", "-K", psk.hex(), "-iv", nonce.hex()],
                        input=data, capture_output=True, check=True).stdout
    flags = (a.hop_limit & 0x07) | ((a.hop_limit & 0x07) << 5)     # hop_limit | hop_start, want_ack and via_mqtt off
    header = (to.to_bytes(4, "little") + frm.to_bytes(4, "little") + pid.to_bytes(4, "little")
              + bytes([flags, 0x08, 0x00, 0x00]))                  # flags, channel hash, next_hop, relay
    frame = header + ct
    if len(frame) % 2:
        # GUARDRAIL: an odd CREATE block leaves HERE odd and every later definition is refused with ERR_DICT (R28).
        raise SystemExit(f"frame is {len(frame)} B - odd; change the text length")
    OUT.write_text(json.dumps({
        "plain": data.hex(), "nonce": nonce.hex(), "ct": ct.hex(), "header": header.hex(),
        "frame": frame.hex(), "from_": frm, "to": to, "id": pid, "psk": DEFAULT_PSK, "text": a.text,
        "channel_hash": 0x08, "portnum": a.portnum, "flags": flags,
        "note": "measured from a captured real packet: Data is encrypted, channel hash 0x08",
    }, indent=2) + "\n")
    print(f"  header {header.hex()}  data {data.hex()}  ct {ct.hex()}  frame {len(frame)} B")


if __name__ == "__main__":
    sys.exit(main())
