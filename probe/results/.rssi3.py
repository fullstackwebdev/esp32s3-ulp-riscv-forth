import sys, pathlib, re, time
sys.path.insert(0, "probe/repl/tools")
from devio import Dev
def load(dev, path):
    pend, name = [], None
    for raw in pathlib.Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("\\"): continue
        m = re.match(r":\s+(\S+)", line)
        if m and not pend: name = m.group(1)
        if name:
            pend.append(line)
            if line.endswith(";"):
                for one in pend: dev.cmd(one, 8.0, allow_error=True)
                pend, name = [], None
            continue
        dev.cmd(line, 8.0, allow_error=True)
B = Dev(port="/dev/ttyUSB1"); B.reset()
load(B, "examples/apps/lora/lora1.fs"); load(B, "examples/apps/lora/lora_rx.fs")
B.num("INIT .", 8.0)
B.cmd("RC SR", 6.0, allow_error=True)
# Sample the radio's own instantaneous RSSI as fast as the console allows, for 14 s (A transmits every 5 s).
t0 = time.time()
vals = []
while time.time() - t0 < 14:
    vals.append((round(time.time() - t0, 1), B.num("NSSLO 21 >BYTE RD-BYTE NSSHI .", 5.0)))
print("samples:", len(vals))
print("distinct values:", sorted({v for _, v in vals}))
print("first 12:", vals[:12])
print("non-floor samples (>3 from median):", [v for v in vals if abs(v[1] - vals[len(vals)//2][1]) > 3][:10])
