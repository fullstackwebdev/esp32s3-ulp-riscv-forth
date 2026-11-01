#!/usr/bin/env python3
"""devio.py — fast, prompt-driven device IO for the ULP console, plus timing.

GUARDRAIL: every probe used to sleep for a fixed 0.25-0.6 s after each command, and a run issues hundreds of them.
Measured: 370 ms per command with a 0.35 s drain versus 20 ms when reading until the machine's own end-of-line
marker - 18.6x, which is the difference between a 3-minute device run and a 10-second one. Timing out on a slow
reply must still be an ERROR, not a silent short read: `cmd()` raises on timeout, and callers that expect an error
marker may pass `allow_error=True`.

GUARDRAIL: seeding is batched but never fire-and-forget. A previous fire-and-forget loop silently dropped blocks, and
a block that was never written looks exactly like a phase bug three blocks later. `seed_many()` writes in batches,
then verifies every acknowledgement and retries only what is missing.

GUARDRAIL: a hard reset is required per *variant*, not per command: without it the previous variant's SEALed, rewound
dictionary is still in RAM. `Dev.reset()` costs ~2 s, so it is explicit and never hidden inside `cmd()`.
"""
import os
import re
import select
import subprocess
import termios
import time

PORT = "/dev/ttyACM1"
OK = "ok"


class Timeout(RuntimeError):
    pass


class Dev:
    def __init__(self, port=PORT, quiet=False):
        self.port = port
        self.quiet = quiet
        self.fd = None

    # ---- lifecycle ------------------------------------------------------------------------------------------
    def reset(self, settle=2.0):
        subprocess.run(["python3", "-m", "esptool", "--port", self.port, "--after", "hard_reset", "chip_id"],
                       capture_output=True)
        time.sleep(settle)
        if self.fd is not None:
            self.close()
        self.fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY)
        t = termios.tcgetattr(self.fd)
        t[0] = 0
        t[1] = 0
        t[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        t[3] = 0
        t[4] = t[5] = termios.B115200
        t[6][termios.VMIN] = 0
        t[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, t)
        time.sleep(1.0)
        self.drain(0.5)

    def hard_reset_capture(self, seconds=4.0):
        """GUARDRAIL: esptool-based reset() closes the port, so the ROM boot log - the only record of why a wedged board
        restarted - was lost every time. Toggle EN via RTS while HOLDING the port, and read the boot text as it arrives."""
        import fcntl, struct
        TIOCM_DTR, TIOCM_RTS = 0x002, 0x004
        fcntl.ioctl(self.fd, termios.TIOCMBIC, struct.pack("I", TIOCM_DTR))
        fcntl.ioctl(self.fd, termios.TIOCMBIS, struct.pack("I", TIOCM_RTS))   # RTS -> EN low: reset
        time.sleep(0.15)
        fcntl.ioctl(self.fd, termios.TIOCMBIC, struct.pack("I", TIOCM_RTS))
        buf, end = b"", time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if r:
                try: buf += os.read(self.fd, 4096)
                except BlockingIOError: pass
        return buf.decode(errors="replace")

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        self.reset()
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- raw read -------------------------------------------------------------------------------------------
    def preflight(self, words):
        """GUARDRAIL: an undefined word made the harness report "no number" twice, which reads like a loader fault and cost
        two chip sessions. Ask the device about every word first: `' W .` answers an xt, or `W?` for a missing word."""
        missing = []
        for w in words:
            lines = [s.strip() for s in self.cmd(f"' {w} .", timeout=3.0).splitlines() if s.strip()]
            # GUARDRAIL: the device prints the number and `ok` on ONE line ("52 ok"), so a line must merely CONTAIN a
            # number. Both earlier versions were wrong: "last line is numeric" and "a line of only digits". Real
            # transcripts are the fixtures now (tests/preflight_dry.py); the fixture, not the board, was the lie.
            if not any(re.search(r"-?\d", s) for s in lines) or any(s.endswith("?") for s in lines):
                missing.append(w)
        if missing:
            raise RuntimeError(f"preflight: words missing on the device: {missing} - fix the harness, not the firmware")
        return True

    def drain(self, quiet=0.5, cap=10.0):
        buf = b""
        end = time.time() + cap
        last = time.time()
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.01)
            if r:
                c = os.read(self.fd, 4096)
                if c:
                    buf += c
                    last = time.time()
            elif time.time() - last > quiet:
                break
        return buf.decode("ascii", "replace")

    # GUARDRAIL: a refusal from the console (`line too long: ... NOT sent`) carries neither `ok` nor `?`, so it
    # timed out instead of being reported. Every console-side message must be a completion marker.
    def cmd(self, line, timeout=5.0, allow_error=False, # GUARDRAIL: `#i`/`#u` answer with "info:" and return WITHOUT an `ok`, so the default markers never matched and a
            # harness call waited until timeout while the answer was already in the buffer. Give the harness the real marker.
            markers=(OK, "?", "ERR_", "NOT sent", "blocks from block", "adopted", "REFUSED", "poke:", "stall:", "img:",
                     "info:")):
        """Send one line, read until the prompt marker (ok) or an error (?), return the transcript."""
        os.write(self.fd, line.encode() + b"\r")
        buf = ""
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.01)
            if r:
                c = os.read(self.fd, 4096)
                if not c:
                    continue
                buf += c.decode("ascii", "replace")
                if ("ERR_BUSY" in buf or "NO_SERVER" in buf):
                    # GUARDRAIL: a wedged block layer makes every later command fail for the wrong reason; clear it
                    # here so the next call measures the machine rather than the latch.
                    try:
                        os.write(self.fd, b"0 2 BLKXFER\r"); time.sleep(0.05); self.drain(0.02, 0.5)
                    except Exception:
                        pass
                if any(m in buf for m in markers):
                    # one short settle read so a second line of output is not lost
                    buf += self.drain(0.02, 0.5)
                    if "?" in buf and not allow_error:
                        # an error marker may legitimately be the expected result; let callers decide
                        return buf
                    return buf
        raise Timeout(f"no reply to {line!r} within {timeout}s; got {buf[-60:]!r}")

    def abort_block(self):
        """Clear a latched block failure. GUARDRAIL: one write to a silent block wedges every later block call with
        ERR_BUSY until reset (measured: a write to fixture block 5 answered ERR_NO_SERVER and every following block op
        failed). The escape hatch is `0 2 BLKXFER` (op 2 = BLK_ABORT); the harness sends it instead of rebooting."""
        try:
            self.cmd("0 2 BLKXFER", markers=("ok", "?", "NOT sent"))
        except Exception:
            pass

    # ---- convenience -----------------------------------------------------------------------------------------
    @staticmethod
    def nums(text):
        return [int(x) for x in re.findall(r"-?\d+", text)]

    def num(self, line, timeout=5.0):
        n = self.nums(self.cmd(line, timeout))
        if not n:
            raise Timeout(f"no number in reply to {line!r}")
        return n[-1]

    def timed(self, line, timeout=10.0):
        t0 = time.monotonic()
        out = self.cmd(line, timeout)
        return time.monotonic() - t0, out

    # ---- seeding ---------------------------------------------------------------------------------------------
    def seed(self, block, text, tries=4):
        hexs = text.encode().hex()
        for _ in range(tries):
            # GUARDRAIL: the seeder acknowledges with `seed: block N <- M bytes`, which is neither `ok` nor an
            # error. Waiting only for ok/? timed out on every seed (5 s each) and looked like a dead board.
            out = self.cmd(f"#b {block} {hexs}", markers=("bytes", OK, "?"))
            if f"seed: block {block} <-" in out:
                return True
        return False

    def seed_many(self, items):
        """items: [(block, text), ...].

        GUARDRAIL: seeding is UART-TRANSMIT-bound, not round-trip-bound: a 128-byte block travels as 256 hex chars, so
        ~30 ms per block is the wire, not the machine. Measured: per-line 30 ms/block; a batch-then-reverify version was
        54 ms/block - SLOWER, because the extra verification pass cost more than the round trips it saved. So this
        sends everything and reads ONE transcript, counting the acks, then retries only the blocks that never
        acknowledged. That is the cheapest correct form; do not add a per-block re-verification pass.
        """
        items = list(items)
        pending = list(items)
        for _ in range(3):
            for blk, text in pending:
                os.write(self.fd, f"#b {blk} {text.encode().hex()}".encode() + b"\r")
            out = self.drain(0.4, 10.0 + 0.03 * len(pending))
            pending = [(b, t) for b, t in pending if f"seed: block {b} <-" not in out]
            if not pending:
                return []
        return [b for b, _ in pending]

    # ---- timing helpers --------------------------------------------------------------------------------------
    def stats(self, label, samples):
        if not samples:
            return f"{label}: no samples"
        s = sorted(samples)
        return (f"{label}: n={len(s)} min={s[0]*1000:.1f} med={s[len(s)//2]*1000:.1f} "
                f"max={s[-1]*1000:.1f} ms")
