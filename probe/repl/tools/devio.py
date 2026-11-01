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
        """Hard reset through esptool, then WAIT FOR THE MACHINE TO ANSWER instead of sleeping a guessed number.

        GUARDRAIL: the old body was `sleep(settle)` + `sleep(1.0)` + `drain(0.5)` - 2.7 s of pure waiting on top of
        esptool, and it was still a guess: too short on a slow boot and pure waste on a fast one. Measured, `./cli.py
        --library` spent 6.9 s in connect of which ~2.7 s was these sleeps. A readiness probe (ask `HERE .` until it
        answers) costs 40 ms per answer and returns the moment the board is up; the fixed sleep is only a floor.
        """
        subprocess.run(["python3", "-m", "esptool", "--port", self.port, "--after", "hard_reset", "chip_id"],
                       capture_output=True)
        time.sleep(min(settle, 0.25))            # a floor: the probe below decides, not a number
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
        self.drain(0.05, 0.3)                    # boot chatter, but do not pay 0.5 s for it
        # GUARDRAIL: fail LOUDLY if the board never answers: a reset that silently returns leaves every caller reading
        # boot text as if it were a reply, which is the class of bug the freshness check in cli.connect exists for.
        end = time.time() + 5.0
        while time.time() < end:
            try:
                self.num("HERE .", timeout=0.5)
                return
            except Exception:
                time.sleep(0.05)
        raise Timeout(f"{self.port} did not answer after a hard reset within 5 s")

    def pulse_reset(self, settle=0.9):
        """Reset the board by pulsing EN on the RTS line, holding the port open. VERIFIED: if the pulse did not reset the
        machine, fall back to esptool's hard reset, because a reset that did not happen is worse than a slow one.

        GUARDRAIL: esptool's hard reset costs ~2.5 s per invocation because it re-opens the port and talks the bootloader
        protocol - measured in cli.py's startup. A DTR/RTS pulse was believed to do the same reset in ~50 ms, and on a
        board with a USB-UART bridge it does. On THIS board it does NOT: measured with `: ZZZZ 1 ;` (HERE 794) followed
        by a pulse, HERE stayed 794, while esptool's hard reset returned it to the baked 786. The chip exposes
        USB-Serial-JTAG, whose DTR/RTS are emulated registers rather than a physical EN line, so the modem bits are
        simply not connected to the reset. Every test paid for two of those no-ops, and worse, a caller that assumed
        "pulsed = fresh" was reading the PREVIOUS run's dictionary.
        """
        import fcntl, struct
        TIOCM_DTR, TIOCM_RTS = 0x002, 0x004
        if self.fd is None:
            self.fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY)
            a = termios.tcgetattr(self.fd)
            a[0] = 0; a[1] = 0
            a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            a[3] = 0
            a[4] = a[5] = termios.B115200
            a[6][termios.VMIN] = 0; a[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, a)
        else:
            self.drain(0.05, 1.0)
        # GUARDRAIL: DTR must be HIGH while EN pulses. DTR is wired to IO0 on these boards, so DTR low at the EN edge puts
        # the chip in the DOWNLOAD BOOTLOADER: measured, the board went silent after a pulse and only esptool could talk
        # to it. Clearing DTR (low) is what esptool does to ENTER the bootloader - here we want the opposite.
        fcntl.ioctl(self.fd, termios.TIOCMBIS, struct.pack("I", TIOCM_DTR))   # IO0 high = boot the app
        fcntl.ioctl(self.fd, termios.TIOCMBIS, struct.pack("I", TIOCM_RTS))   # EN low = reset
        time.sleep(0.12)
        fcntl.ioctl(self.fd, termios.TIOCMBIC, struct.pack("I", TIOCM_RTS))   # EN high = start
        time.sleep(settle)
        self.drain(0.15, 3.0)
        # GUARDRAIL: verify, then fall back. A fresh boot reports the baked HERE (786 here); anything at or above 900 means
        # the machine never restarted (see the class-level note above for the measurement). No answer is also a failure.
        try:
            here = self.num("HERE .", timeout=0.6)
        except Exception:
            here = None
        if here is None or here >= 900:
            self.reset(settle=settle)

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
            # GUARDRAIL: leave the board in the RUN state. DTR is wired to IO0 and RTS to EN; a script that exits with
            # IO0 low leaves the next reset selecting the DOWNLOAD BOOTLOADER, which looks exactly like a dead board
            # (measured twice: silent on every port, recovered only by reflashing or a reset that happened to hit the
            # right edge). Drive IO0 high and release EN before closing.
            try:
                import fcntl, struct
                TIOCM_DTR, TIOCM_RTS = 0x002, 0x004
                fcntl.ioctl(self.fd, termios.TIOCMBIS, struct.pack("I", TIOCM_DTR))
                fcntl.ioctl(self.fd, termios.TIOCMBIC, struct.pack("I", TIOCM_RTS))
            except Exception:
                pass
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
    def cmd(self, line, timeout=5.0, allow_error=False, settle=0.02, # GUARDRAIL: `#i`/`#u` answer with "info:" and return WITHOUT an `ok`, so the default markers never matched and a
            # harness call waited until timeout while the answer was already in the buffer. Give the harness the real marker.
            markers=(OK, "?", "ERR_", "NOT sent", "blocks from block", "adopted", "REFUSED", "poke:", "stall:", "img:",
                     "info:", "mem:", "cmp:", "stack:", "seed:", "dump:")):
        """Send one line, read until the prompt marker (ok) or an error (?), return the transcript.

        GUARDRAIL: `settle` is the quiet window after the marker, and it costs 20 ms on EVERY command - 34 blocks of
        `LOAD` in a library build is 0.7 s of waiting for a second line that a LOAD never sends. Callers that know the
        reply is exactly one line (a compile, a seed ack) pass a small value; everything else keeps the default so a
        two-line answer is not truncated. Measured: a bare round trip is 40 ms, so this window is a third of a LOAD.
        """
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
                    buf += self.drain(settle, 0.5)
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
        """items: [(block, text), ...]. Returns the blocks that were NOT seeded exactly; empty means all good.

        GUARDRAIL: seeding is UART-TRANSMIT-bound, not round-trip-bound: a 128-byte block travels as 256 hex chars.
        GUARDRAIL: send in SMALL BATCHES and check the ACK'S BYTE COUNT. A 10-line burst (2.6 KB) lost bytes mid-line on
        the board even with a 4 KB RX ring - measured acks of 64/128, 116/128, 65/77 and one line missing entirely -
        because the reader stalls ~34 ms inside a flash erase. Checking only the ack's PREFIX accepted those short blocks;
        the phase then compiled a truncated source, its image was 135 B instead of 576, and EXECUTE jumped past the
        pasted code into a spin that touched no memory. Count, or do not believe the ack.
        """
        items = list(items)
        pending = list(items)
        BATCH = 4
        for _ in range(5):
            acked = {}                       # GUARDRAIL: accumulate acks across the WHOLE pass. Filtering on the last
                                             # batch's acks alone marked already-seeded blocks as pending (-2, -21).
            for i in range(0, len(pending), BATCH):
                batch = pending[i:i + BATCH]
                for blk, text in batch:
                    os.write(self.fd, f"#b {blk} {text.encode().hex()}".encode() + b"\r")
                out = self.drain(0.08, 6.0)
                acked.update({int(m.group(1)): int(m.group(2))
                              for m in re.finditer(r"seed: block (\d+) <- (\d+) bytes", out)})
            pending = [(b, t) for b, t in pending if acked.get(b) != len(t.encode())]
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
