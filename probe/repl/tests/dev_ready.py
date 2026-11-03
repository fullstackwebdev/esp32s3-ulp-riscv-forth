#!/usr/bin/env python3
"""Return a Dev for a board that is provably answering the REPL, resetting until it does.

GUARDRAIL: typing into a board that has not finished booting leaves a sticky error flag, and every later line then fails
- which makes the NEXT file look broken ("refused at interpret level: 'CREATE TBL'") when the file is fine. That wasted
several measurement rounds. Never load a file without proving the board answers arithmetic first.
"""
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
from devio import Dev                      # noqa: E402


def ready(port, tries=8, settle=4.0):
    last = None
    for _ in range(tries):
        d = Dev(port=port)
        try:
            d.reset()
            time.sleep(settle)
            # GUARDRAIL: the first line after a reset is often swallowed. Send an empty line, then ask something whose
            # answer cannot be confused with boot noise.
            d.cmd("\n", 5.0, allow_error=True)
            time.sleep(0.4)
            # parse the reply as TEXT: nums() raises on boot noise, and a raised parse looked like "not ready" even
            # when the board had answered.
            reply = d.cmd("1 2 + .", 8.0, allow_error=True)
            if "3" in reply.split("\n")[-2:][0] or "3 ok" in reply:
                return d
            last = f"reply {reply.strip()[-40:]!r}"
        except Exception as e:                 # noqa: BLE001 - any failure means "not ready yet"
            last = f"{type(e).__name__}: {e}"
        d.close()
    raise SystemExit(f"{port}: board never became ready ({last})")


def load_ready(port, files, tries=4):
    """Reset, prove the board answers, then load files; retry the whole cycle if a definition is refused.

    GUARDRAIL: right after a flash the board can answer arithmetic and still refuse `CREATE` (ERR_DICT). Treating that as
    "the file is broken" wasted a whole measurement round - retry the reset+load instead of editing working sources.
    """
    from lora_frame_phase import load
    last = None
    for _ in range(tries):
        d = ready(port, tries=3, settle=5.0)
        try:
            for f in files:
                load(d, pathlib.Path(f) if not isinstance(f, pathlib.Path) else f)
            return d
        except SystemExit as e:
            last = str(e)
            d.close()
    raise SystemExit(f"{port}: could not load {files}: {last}")
