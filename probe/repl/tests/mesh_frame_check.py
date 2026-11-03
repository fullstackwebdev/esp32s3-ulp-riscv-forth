#!/usr/bin/env python3
"""Judge our transmit frame with Meshtastic's OWN library, not with our own reading of its sources.

    python3 tests/mesh_frame_check.py [--json tests/data/mesh_packet.json]

Checks, in order:
  1. the clear header is the 16-byte layout the firmware uses (to, from, id, flags, channel, next_hop, relay) and the
     flag bits mean what we think (hop_limit 0-2, want_ack 3, via_mqtt 4, hop_start 5-7);
  2. the ciphertext, decrypted with the nonce/id/from in that header, parses as `mesh_pb2.Data` with the portnum and
     payload we intended - i.e. the bytes a receiver would hand to its router;
  3. the channel byte equals `meshtastic.util.generate_channel_hash(<channel name>, <psk>)`.
"""
import argparse
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_PSK = "d4f1bb3a20290759f0bcffabcf4e6901"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:52s} {detail}")
    if not ok:
        fails.append(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(HERE / "data/mesh_packet.json"))
    ap.add_argument("--channel-name", default="LongFast",
                    help="the name the firmware uses at runtime (it fills it from the preset), not the stored name")
    a = ap.parse_args()
    try:
        from meshtastic import util
        from meshtastic.protobuf import mesh_pb2, portnums_pb2
    except ImportError as e:                                   # pragma: no cover
        raise SystemExit(f"the meshtastic python package is required as the judge: {e}")
    ref = json.loads(pathlib.Path(a.json).read_text())
    frame = bytes.fromhex(ref["frame"])
    hdr, ct = frame[:16], frame[16:]
    to_, frm = int.from_bytes(hdr[0:4], "little"), int.from_bytes(hdr[4:8], "little")
    pid = int.from_bytes(hdr[8:12], "little")
    flags, channel, next_hop, relay = hdr[12], hdr[13], hdr[14], hdr[15]

    check("header carries a non-zero from", frm != 0, f"from={frm:#010x}")
    check("broadcast to", to_ == 0xFFFFFFFF, f"to={to_:#010x}")
    check("hop_limit in range", (flags & 0x07) in (1, 2, 3), f"hop_limit={flags & 0x07}")
    # GUARDRAIL: a receiver drops a packet whose hop_start is 0 (it looks like it has already been relayed to death),
    # so hop_start must be set and no larger than hop_limit.
    check("hop_start set and <= hop_limit", 0 < ((flags >> 5) & 0x07) <= (flags & 0x07),
          f"hop_start={(flags >> 5) & 0x07}")
    check("want_ack and via_mqtt clear", not (flags & 0x08) and not (flags & 0x10), f"flags={flags:#04x}")
    check("next_hop and relay zero", next_hop == 0 and relay == 0)

    nonce = pid.to_bytes(8, "little") + frm.to_bytes(4, "little") + bytes(4)
    check("nonce is id||from||4 zero bytes", nonce.hex() == ref["nonce"], nonce.hex())
    pt = subprocess.run(["openssl", "enc", "-aes-128-ctr", "-d", "-K", DEFAULT_PSK, "-iv", nonce.hex()],
                        input=ct, capture_output=True, check=True).stdout
    data = mesh_pb2.Data()
    try:
        data.ParseFromString(pt)
        parsed = True
    except Exception as e:                                     # pragma: no cover
        parsed, data = False, None
        print(f"        protobuf error: {e}")
    check("ciphertext decrypts to a valid Data message", parsed and pt == bytes.fromhex(ref["plain"]), pt.hex())
    if parsed:
        check("portnum is TEXT_MESSAGE_APP",
              data.portnum == portnums_pb2.PortNum.TEXT_MESSAGE_APP,
              f"{data.portnum} = {portnums_pb2.PortNum.Name(data.portnum)}")
        check("payload is the intended text", bytes(data.payload) == ref["text"].encode(),
              repr(bytes(data.payload).decode(errors="replace")))
        # GUARDRAIL: the plaintext is the Data message, NOT a MeshPacket wrapper - proven by decrypting a captured real
        # packet. Re-serialising it must give back the same bytes, or the encoder is not canonical for this schema.
        check("re-encode is byte-identical", data.SerializeToString() == pt)

    psk = bytes.fromhex(DEFAULT_PSK)
    want = util.generate_channel_hash(a.channel_name, psk)
    check(f"channel byte == meshtastic's hash of {a.channel_name!r}", channel == want,
          f"frame {channel:#04x}, their library {want:#04x}")

    print(f"\n  {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
