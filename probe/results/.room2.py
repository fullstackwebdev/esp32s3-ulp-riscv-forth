import sys, pathlib, re
sys.path.insert(0, "probe/repl/tools"); sys.path.insert(0, ".")
from devio import Dev

def load(dev, path, label):
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
                if not dev.nums(dev.cmd("' " + name + " .", 5.0, allow_error=True)):
                    print(f"  {label}: {name} REFUSED")
                pend, name = [], None
            continue
        dev.cmd(line, 8.0, allow_error=True)

d = Dev(port="/dev/ttyUSB1"); d.reset()
load(d, "examples/apps/lora/lora1.fs", "tx")
print("after lora1 : HERE =", d.num("HERE ."), "LATEST =", d.num("LATEST ."))
load(d, "examples/apps/lora/lora_rx.fs", "rx")
print("after lora_rx: HERE =", d.num("HERE ."), "LATEST =", d.num("LATEST ."))
print("INIT ->", d.num("INIT .", 8.0), " RX1 ->", d.num("RX1 .", 8.0))
