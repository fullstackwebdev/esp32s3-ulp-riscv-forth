#!/usr/bin/env python3
"""seed_pages.py — put authored pages into the block store.

The contract (docs/26) says a page is **8 consecutive blocks, one block per screen line, up to 70 characters of text,
space-padded**. Authors write `content/<app>/pNN.txt` (one line per block); this tool places page N at
`BASE[app] + N*8` and refuses anything that would not render the way the phase expects.

GUARDRAIL: the line length is checked against the DISPLAY width (70), not the block width (128). A 100-character line
fits a block, seeds without complaint, and then draws past the 70-column bar the launcher and every app share - the
symptom is a ragged screen, not an error, and it would be blamed on the phase. Refuse it here, by name, with the page and
line number.

GUARDRAIL: pages are laid out by ARITHMETIC (base + page*8), never by directory order. Two apps sharing a range, or a gap
in the numbering, would otherwise silently shift every later page by one block - measured shape of the bug: the inbox
shows message 2's body under message 1's subject.

Usage:
    tools/seed_pages.py --dry-run                 what would be written, and to which blocks
    tools/seed_pages.py                            writes them (needs the board, goes through cli.py)
    tools/seed_pages.py --app mail --dry-run       one app
"""
import argparse
import pathlib
import re
import sys

# GUARDRAIL: `parents[1]`, not [2]. This file is <repo>/tools/seed_pages.py, so parents[0] is tools/ and parents[1] is the
# repo; [2] pointed one level ABOVE the repo and the tool reported "content/mail has no pNN.txt files" against a tree that
# had three of them. It survived my own smoke test because I tested a PATCHED COPY in /tmp (where ROOT was hardcoded to the
# repo) - verifying a copy of the artifact instead of the artifact. `--dry-run` now prints the content root it resolved.
ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content"

# The allocation table in docs/26. One base per app; pages are base + page*8.
# GUARDRAIL: these are the CONTENT bases from the re-partitioned table in docs/26, not the old per-app ranges. The first
# version still said mail 40 / gopher 60 / reader 80 - the pre-repartition numbers - so a dry run planned to write mail
# across 40..63 and would have seeded it into calc2's and sheet's descriptor blocks. Only apps with AUTHORED PAGES belong
# in this table: the calculator and the shelf have none (their state is cells), and the sheet's block is data, not pages.
BASE = {"mail": 80, "gopher": 104, "reader": 64}
PAGE_BLOCKS = 8          # a page is 8 blocks
LINE_WIDTH = 70          # the shared display width (examples/menu.fs: FILL is 70)
STORE_BLOCKS = 128


def pages(app, dry_run=True):
    """Yield (page, block, text) for one app, refusing anything the phase could not render."""
    base = BASE[app]
    files = sorted((CONTENT / app).glob("p*.txt"))
    if not files:
        raise SystemExit(f"seed_pages: content/{app}/ has no pNN.txt files - nothing to seed")
    out = []
    for f in files:
        m = re.fullmatch(r"p(\d+)\.txt", f.name)
        if not m:
            raise SystemExit(f"seed_pages: {f} is not named pNN.txt - the page number comes from the NAME, not the order")
        page = int(m.group(1))
        lines = f.read_text().splitlines()
        if len(lines) > PAGE_BLOCKS:
            raise SystemExit(
                f"seed_pages: {f} has {len(lines)} lines, a page is {PAGE_BLOCKS} blocks - split it into two pages")
        for i, line in enumerate(lines):
            if len(line) > LINE_WIDTH:
                raise SystemExit(
                    f"seed_pages: {f}:{i + 1} is {len(line)} characters, the screen is {LINE_WIDTH} - shorten the line "
                    f"(a block holds 128, but every phase draws {LINE_WIDTH})")
            if any(ord(c) < 32 or ord(c) > 126 for c in line):
                bad = [c for c in line if ord(c) < 32 or ord(c) > 126]
                raise SystemExit(
                    f"seed_pages: {f}:{i + 1} has non-printable byte(s) {[hex(ord(c)) for c in bad]} - the store holds "
                    f"printable ASCII; a control byte would draw as a stray escape on the operator's terminal")
            blk = base + page * PAGE_BLOCKS + i
            if blk >= STORE_BLOCKS:
                raise SystemExit(f"seed_pages: {f} page {page} line {i + 1} needs block {blk}, the store ends at "
                                 f"{STORE_BLOCKS - 1} - check the allocation table in docs/26")
            out.append((page, blk, line))
    return out


def main(argv):
    ap = argparse.ArgumentParser(description="seed authored pages into the block store (docs/26 content format)")
    ap.add_argument("--app", action="append", choices=sorted(BASE), help="seed only this app (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    ap.add_argument("--port", default="/dev/ttyACM1")
    a = ap.parse_args(argv)

    apps = a.app or [p.name for p in sorted(CONTENT.glob("*")) if p.is_dir() and p.name in BASE]
    if not apps:
        raise SystemExit("seed_pages: no content/ directories to seed")
    plan, seen = {}, {}
    for app in apps:
        rows = pages(app)
        for _page, blk, _text in rows:
            if blk in seen:
                raise SystemExit(f"seed_pages: block {blk} would be written twice ({seen[blk]} and {app}) - the "
                                 f"allocation table in docs/26 gives each app its own range")
            seen[blk] = app
        plan[app] = rows
        print(f"  {app}: {len({p for p, _, _ in rows})} page(s), {len(rows)} line(s), blocks "
              f"{BASE[app]}..{BASE[app] + PAGE_BLOCKS * (max(p for p, _, _ in rows) + 1) - 1}")
    if a.dry_run:
        print(f"  content root: {CONTENT}")
        for app, rows in plan.items():
            for page, blk, text in rows:
                print(f"    {app} p{page} block {blk:3d}: {text}")
        return 0

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "probe" / "repl" / "tools"))
    import cli

    dev = cli.connect(a.port, 1.0)
    if not dev:
        return 4
    try:
        items = [(blk, text) for rows in plan.values() for _page, blk, text in rows]
        missing = dev.seed_many(items)
        if missing:
            raise SystemExit(f"seed_pages: block(s) {missing} did not acknowledge - nothing is claimed as seeded")
        # GUARDRAIL: `#d` descriptors live in the same flash sector cache as block writes; the store only reaches flash on
        # a flush. Seeding without `#f` looks correct on the board and is gone after a power cycle (measured by lane R).
        dev.cmd("#f", timeout=30.0, allow_error=True)
        print(f"seed_pages: {len(items)} line(s) into {len(plan)} app(s), flushed to flash")
    finally:
        dev.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
