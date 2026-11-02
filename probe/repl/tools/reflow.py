#!/usr/bin/env python3
"""reflow.py - wrap `\\` comment lines to the device's 63 B ring limit.

    python3 tools/reflow.py FILE.fs [FILE.fs ...]

WHY: a typed line over CMD_SIZE-1 = 63 B is REFUSED by the ring SILENTLY, so the phrase simply never reaches the
machine and the definition does not exist. Comments are lines too, and they are the lines that grow unwatched -
R21 fired on comment lines four times in one LoRa session.

GUARDRAIL: only `\\` lines are touched, and only their TEXT is rewrapped; code lines, indentation and blank lines
are left exactly as they are. A tool that reflows code would break the one-line control-structure rule (R29) that
the engine depends on.
"""
import sys
import textwrap


def reflow(text, width=61):
    out, buf = [], []

    def flush():
        nonlocal buf
        if not buf:
            return
        for ln in textwrap.wrap(" ".join(buf), width, break_long_words=False, break_on_hyphens=False):
            out.append("\\ " + ln)
        buf = []

    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("\\"):
            body = s[1:].strip()
            if body:
                buf.append(body)
            elif buf:
                flush()
                out.append("\\")
            else:
                out.append("\\")
            continue
        flush()
        out.append(line)
    flush()
    return "\n".join(out) + "\n"


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    worst = 0
    for path in argv:
        text = open(path).read()
        new = reflow(text)
        if new != text:
            open(path, "w").write(new)
        over = [l for l in new.split("\n") if len(l) > 63]
        worst = max(worst, len(over))
        print(f"  {path}: {'rewrapped' if new != text else 'unchanged'}"
              + (f", {len(over)} line(s) still over 63 B" if over else ", every line <= 63 B"))
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
