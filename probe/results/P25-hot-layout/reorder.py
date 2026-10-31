#!/usr/bin/env python3
"""P25: re-emit the OS layer with the idle path's definitions contiguous.

Order is the ONLY thing this script changes: it parses each P24 source file into whole definitions
(leading `\\` comments travel with the definition they introduce, so the text stays verbatim), then
writes os_hot.fs (the idle block, in dependency order) followed by os_cold.fs (everything else, in
P24's file order). It then asserts the multiset of definition texts is identical before and after,
which is what makes "order only, not content" a checkable claim rather than a promise.

GUARDRAIL: a definition chunk has to end at the line carrying the closing `;`, not at the next line
that starts with `:` — EMIT-EVENT and POLL-EVENTS both contain `\\` comment lines and multi-line
bodies, and a line-based split silently truncates them into unparseable fragments.
"""
import pathlib, re, sys

root = pathlib.Path(__file__).resolve().parent
SRC = ["os_tasks.fs", "os_events.fs", "os_repl.fs", "os_introspect.fs", "os_device.fs"]

NAME = re.compile(r"^:\s+(\S+)|^(?:CREATE|VARIABLE)\s+(\S+)|^\S+\s+CONSTANT\s+(\S+)")


def ends(raw):
    """Does this line close a definition? Asked of the code part only.

    GUARDRAIL: `\` comments do not end at the `;` — `: PAUSE  YIELD ;   \ give the queue a turn`
    ends in "turn", so testing the raw line left PAUSE open and it swallowed the next two
    definitions (SLEEP-TICKS vanished from the hot block without a parse error).
    """
    return raw.split("\\")[0].rstrip().endswith(";")


def chunks(text):
    """[(name, text)] in file order; comments attach to the definition that follows them.

    GUARDRAIL: a CONSTANT/CREATE/VARIABLE defines in ONE line and has no `;`, so it must close on
    the line that names it — waiting for `;` swallowed every constant into the next definition and
    the layer then lost 36 names without a single parse error.
    """
    out, pend = [], []
    cur, name = None, None
    for raw in text.splitlines():
        if cur is None:
            m = NAME.match(raw.strip())
            if not m:
                pend.append(raw)                    # `\` comment / blank: waits for its definition
                continue
            name = next(g for g in m.groups() if g)
            cur = [raw]
            if ends(raw) or not raw.lstrip().startswith(":"):
                out.append((name, "\n".join(pend + cur)))
                cur, pend, name = None, [], None
        else:
            cur.append(raw)
            if ends(raw):
                out.append((name, "\n".join(pend + cur)))
                cur, pend, name = None, [], None
    if cur:
        sys.exit("unterminated definition: " + name)
    return out


# The idle path, in emission order. Data first (it must exist before the code that addresses it),
# then poll -> dispatch -> task switch -> sleep check.
HOT = """VARIABLE ALLOT CELLS TASK-SZ
T>NEXT T>DSP T>RSP T>IP T>STATE T>WAKE T>WAIT T>USER
#FREE #READY #SLEEP #BLOCK #DEAD #MAXTASK
TASK-POOL RUNQ CUR #TASKS TICK TMP DIAG WM
#EVQ EV-SZ #EV-KEY #EV-GPIO #EV-TICK EV-RING
EV-H EV-T EV-N EA EN KIN GPIOMASK GPIOXT
EV! T-STATE!
NEXT-TASK TICK+ WAKE-1 WAKE-ALL YIELD
WAKE-MASK ON-GPIO EV-GPIO-DO POLL-EVENTS
PAUSE SLEEP-TICKS""".split()

all_chunks = {}
order = []
for f in SRC:
    for nm, txt in chunks((root / f).read_text()):
        if nm in all_chunks:
            sys.exit(f"duplicate definition {nm}")
        all_chunks[nm] = (f, txt)
        order.append(nm)

missing = [h for h in HOT if h not in all_chunks]
if missing:
    sys.exit("hot names not defined in the layer: " + " ".join(missing))
cold = [n for n in order if n not in set(HOT)]

# GUARDRAIL: TIBSZ is 80, so every generated line must stay under it - a 91-char banner line
# aborted the whole build with "os_hot.fs:1: line too long (91 >= 80)" and no dictionary at all.
hdr = ("\\ {name} - P25 reorder. P24's definitions verbatim, order only.\n"
       "\\ Idle block: poll -> dispatch -> task switch -> sleep check.\n")
for fname, names, title in (("os_hot.fs", HOT, "hot"), ("os_cold.fs", cold, "cold")):
    body = hdr.format(name=fname) + \
        "".join(all_chunks[n][1] + "\n" for n in names)
    (root / fname).write_text(body)
    print(f"{fname}: {len(names)} definitions")

# order-only proof: same multiset of definition texts, same names
before = sorted(t for _, t in all_chunks.values())
# re-parse what was written, minus the two generated header lines each file carries
after = sorted(t for f in ("os_hot.fs", "os_cold.fs")
               for _, t in chunks("\n".join((root / f).read_text().splitlines()[2:])))
print(f"definitions before {len(before)}, after {len(after)}, identical text: {before == after}")
if before != after:
    sys.exit("CONTENT CHANGED - the reorder is not order-only")
