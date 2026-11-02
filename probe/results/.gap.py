import sys, pathlib, re
sys.path.insert(0, "probe/repl/tools"); sys.path.insert(0, ".")
from devio import Dev
d = Dev(port="/dev/ttyUSB1"); d.reset()
print("fresh   : HERE=%d LATEST=%d  free=%d" % (d.num("HERE ."), d.num("LATEST ."), d.num("LATEST .") - d.num("HERE .")))
def load(path):
    pend, name = [], None
    for raw in pathlib.Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("\\"): continue
        m = re.match(r":\s+(\S+)", line)
        if m and not pend: name = m.group(1)
        if name:
            pend.append(line)
            if line.endswith(";"):
                for one in pend: d.cmd(one, 8.0, allow_error=True)
                pend, name = [], None
            continue
        d.cmd(line, 8.0, allow_error=True)
load("examples/apps/lora/lora1.fs")
h, l = d.num("HERE ."), d.num("LATEST .")
print("driver  : HERE=%d LATEST=%d  free=%d" % (h, l, l - h))
print("SEAL -> ", d.cmd("SEAL", 20.0, allow_error=True).strip()[-20:])
print("phase window (LATEST-bh) =", d.num("LATEST .") - d.num("bh @ ."))
