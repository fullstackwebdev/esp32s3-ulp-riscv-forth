#!/usr/bin/env python3
"""Read a stock node's OWN radio counters over the air: num_packets_rx, num_packets_rx_bad, noise_floor.

    python3 tests/mesh_peer_stats.py --port /dev/ttyUSB0 --dest '!02AAAAAA'

This is the only witness that separates "its radio never demodulated our frame" from "it demodulated and rejected it":
`num_packets_rx_bad` counts frames whose CRC failed, `num_packets_rx` all demodulated ones, `noise_floor` whether our
carrier raises the floor at all. The requesting node must be running Meshtastic; the peer answers with a Telemetry
packet carrying `local_stats`.

GUARDRAIL: the reply is asynchronous and only arrives if the request sets want_response (request_id). A request that
just prints "Sending packet" proves nothing - this waits on the pubsub topic and fails loudly if no reply lands.
"""
import argparse
import json
import pathlib
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE / "data/peer_stats.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--dest", default="!02AAAAAA")
    ap.add_argument("--wait", type=float, default=45.0)
    a = ap.parse_args()

    import meshtastic.serial_interface
    from pubsub import pub
    from meshtastic.protobuf import telemetry_pb2, portnums_pb2

    got = {}
    done = threading.Event()

    def on_telemetry(packet, interface):
        decoded = packet.get("decoded") or {}
        if decoded.get("portnum") != "TELEMETRY_APP":
            return
        t = telemetry_pb2.Telemetry()
        t.ParseFromString(decoded["payload"])
        variant = t.WhichOneof("variant")           # python protobuf has no `which_variant` (that is the C API)
        print(f"  reply variant {variant} from {packet.get('from')}")
        if variant == "local_stats":
            ls = t.local_stats
            got.update({
                "from": packet.get("from"), "uptime_seconds": ls.uptime_seconds,
                "num_packets_tx": ls.num_packets_tx, "num_packets_rx": ls.num_packets_rx,
                "num_packets_rx_bad": ls.num_packets_rx_bad, "num_rx_dupe": ls.num_rx_dupe,
                "noise_floor": ls.noise_floor, "channel_utilization": round(ls.channel_utilization, 3),
                "num_total_nodes": ls.num_total_nodes,
            })
            done.set()

    pub.subscribe(on_telemetry, "meshtastic.receive.telemetry")
    iface = meshtastic.serial_interface.SerialInterface(a.port)
    try:
        # GUARDRAIL: an EMPTY payload asks for device metrics. The local-stats variant must be present in the request
        # (`Telemetry{local_stats:{}}` = 32 00), otherwise the module answers a different variant and the counters we
        # actually want never arrive.
        iface.sendData(b"\x32\x00", destinationId=a.dest,
                       portNum=portnums_pb2.PortNum.TELEMETRY_APP, wantResponse=True)
        if not done.wait(a.wait):
            print("  NO REPLY - the peer did not answer the local-stats request")
            return 1
        print("  " + json.dumps(got))
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(got, indent=2) + "\n")
        return 0
    finally:
        iface.close()


if __name__ == "__main__":
    sys.exit(main())
