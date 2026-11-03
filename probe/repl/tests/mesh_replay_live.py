#!/usr/bin/env python3
"""Replay a frame the stock node itself transmitted, captured byte-for-byte off the air.

    python3 tests/mesh_replay_live.py [--ours /dev/ttyUSB1] [--peer /dev/ttyUSB0]

Why this exists: it separates two failures that look identical from the outside.

  * If the stock receiver does not react even to its OWN packet, replayed with the same carrier, sync and modem
    parameters, then its receive path is not reaching our transmission at all (RF/state), and no amount of frame
    surgery in our code can fix it.
  * If it reacts (a log line, a duplicate, a node update), then its receiver DOES hear us and the fault is in the
    contents of the frame we normally send (channel hash, decryption, header fields) - a completely different bug,
    in our code.

The peer runs with `security.debug_log_api_enabled` so its own device log arrives over the API; the log is the verdict,
not our inference.
"""
import argparse
import pathlib
import re
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE))
from dev_ready import ready                      # noqa: E402
from lora_frame_phase import load                # noqa: E402

LORA = REPO / "examples/apps/lora"
TEMPLATE = LORA / "loratx_ms_hp.fs"


def capture_frame(dev, peer_port, tries=10):
    """Receive one frame from the peer and return its bytes."""
    load(dev, LORA / "lorainit.fs")
    load(dev, LORA / "lora_rx.fs")
    if dev.num("RADIO-INIT .", 60.0) != 1:
        raise SystemExit("our board: RADIO-INIT failed for the receive phase")
    for n in range(tries):
        dev.cmd("RC SR", 10.0, allow_error=True)
        subprocess.run(["meshtastic", "--port", peer_port, "--sendtext", f"capture {n}"],
                       capture_output=True, timeout=200)
        irq, deadline = 0, time.time() + 10
        while time.time() < deadline:
            irq = dev.num("IQ .", 20.0)
            if irq & 2:
                break
            time.sleep(0.04)
        if not (irq & 2):
            continue
        rep = dev.cmd("RL RB RC", 25.0, allow_error=True)
        # GUARDRAIL: the REPL echoes the typed line, so the echoed numbers must be dropped before parsing or the dump is
        # shifted by the command's own arguments (this exact mistake produced a fake 0x3F on every register read).
        out = [l for l in rep.splitlines()[1:] if l.strip() and l.strip() != "ok"]
        nums = [int(x) for x in re.findall(r"\d+", " ".join(out))]
        if len(nums) >= 32:
            return nums[:32]
    raise SystemExit("our board never decoded a frame to replay")


def build_replay(frame):
    src = TEMPLATE.read_text()
    block = src.split("CREATE FRM", 1)[1]
    head, rest = block.split("\n", 1)
    body, tail = rest.split(";", 1) if ";" in rest else (rest, "")
    # rebuild the FRM body: 6 bytes per line, same shape as the original
    lines = ["  " + " ".join(f"{b} C," for b in frame[i:i + 6]) for i in range(0, len(frame), 6)]
    out = src.split("CREATE FRM", 1)[0] + "CREATE FRM\n" + "\n".join(lines) + "\n" + tail
    path = REPO / "examples/apps/lora/loratx_replay_live.fs"
    path.write_text(out)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", default="/dev/ttyUSB1")
    ap.add_argument("--peer", default="/dev/ttyUSB0")
    a = ap.parse_args()

    logpath = REPO / "probe/results/replay_devlog.txt"
    subprocess.run(["tmux", "kill-session", "-t", "replaylog"], capture_output=True)

    d = ready(a.ours)
    frame = capture_frame(d, a.peer)
    print("  captured frame:", " ".join(f"{b:02x}" for b in frame))
    d.close()

    subprocess.run(["tmux", "new-session", "-d", "-s", "replaylog",
                    f"cd {REPO} && timeout 120 meshtastic --port {a.peer} --listen --debug > {logpath} 2>&1"])
    time.sleep(20)

    path = build_replay(frame)
    print("  replay source:", path.name)
    subprocess.run([sys.executable, str(HERE.parent / "tools/lintgate.py"), "--repl", str(path)],
                   capture_output=True)

    mark = len(logpath.read_text().splitlines()) if logpath.exists() else 0
    d = ready(a.ours)
    load(d, path)
    if d.num("RADIO-INIT .", 60.0) != 1:
        raise SystemExit("our board: RADIO-INIT failed for the replay phase")
    for _ in range(4):
        d.cmd("NSSLO 2 >BYTE 255 >BYTE 255 >BYTE NSSHI", 10.0, allow_error=True)
        d.num("GO .", 120.0)
        time.sleep(1.3)
    d.close()
    time.sleep(30)
    subprocess.run(["tmux", "kill-session", "-t", "replaylog"], capture_output=True)

    tail = logpath.read_text().splitlines()[mark:]
    msgs = [re.search(r'message: "(.*)"', l) for l in tail]
    msgs = [m.group(1) for m in msgs if m]
    print(f"  {len(tail)} new peer log lines, {len(msgs)} device messages")
    for m in msgs[:20]:
        print("   ", m[:120])
    interesting = [m for m in msgs if re.search(r"packet|Ignore|channel|AES|CRC|duplicate|rx", m, re.I)]
    if interesting:
        print("  VERDICT: the stock receiver DID react to its own replayed frame - it hears us; "
              "the fault is in what our normal frame says, not in the RF path.")
        return 0
    print("  VERDICT: the stock receiver reacted to nothing, not even its own packet - its receive path is not "
          "reaching our transmission, so this is an RF/state problem, not frame contents.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
