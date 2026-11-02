import sys, pathlib, re
sys.path.insert(0, "probe/repl/tools"); sys.path.insert(0, ".")
from devio import Dev
d = Dev(port="/dev/ttyUSB1"); d.reset()
def load(path, verbose=False):
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
                    r = d.cmd(one, 8.0, allow_error=True)
                    if verbose: print(f"   sent[{len(one):2d}]: {one[:52]:52s} -> {r.strip().splitlines()[-1][:20] if r.strip() else ''}")
                got = d.nums(d.cmd("' " + name + " .", 5.0, allow_error=True))
                print(f"{name:8s} {'ok' if got else 'ABSENT'}  here={d.num('HERE .')}")
                pend, name = [], None
            continue
        d.cmd(line, 8.0, allow_error=True)
load("examples/apps/lora/lora1.fs")
print("driver loaded, here =", d.num("HERE ."), "latest =", d.num("LATEST ."))
load("examples/apps/lora/lora_rx.fs", verbose=True)
