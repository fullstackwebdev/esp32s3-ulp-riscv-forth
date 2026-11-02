import sys, pathlib, re
sys.path.insert(0, "probe/repl/tools"); sys.path.insert(0, ".")
from devio import Dev

def load(dev, path):
    pend, name = [], None
    for raw in pathlib.Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("\\"):
            continue
        m = re.match(r":\s+(\S+)", line)
        if m and not pend:
            name = m.group(1)
        if name:
            pend.append(line)
            if line.endswith(";"):
                for one in pend:
                    dev.cmd(one, 8.0, allow_error=True)
                pend, name = [], None
            continue
        dev.cmd(line, 8.0, allow_error=True)

d = Dev(port="/dev/ttyUSB1"); d.reset()
print("at reset   HERE =", d.num("HERE ."), "LATEST =", d.num("LATEST ."))
print("report:", " | ".join(x.strip() for x in d.cmd("#k", 8.0, allow_error=True).splitlines() if x.strip())[:140])
load(d, "examples/apps/lora/lora1.fs")
print("after lora1 HERE =", d.num("HERE ."), "LATEST =", d.num("LATEST ."))
print("report:", " | ".join(x.strip() for x in d.cmd("#k", 8.0, allow_error=True).splitlines() if x.strip())[:140])
for w, n in [(": PR1 1 ;", "PR1"), (": PR2 2 ;", "PR2")]:
    d.cmd(w, 5.0, allow_error=True)
    ok = d.nums(d.cmd("' " + n + " .", 5.0, allow_error=True))
    print("  extra", n, "->", "fits" if ok else "REFUSED")
