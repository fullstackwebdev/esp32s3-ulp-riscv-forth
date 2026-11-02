import sys, pathlib, re, time
sys.path.insert(0, "probe/repl/tools"); sys.path.insert(0, ".")
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

A = Dev(port="/dev/ttyUSB0"); A.reset()
B = Dev(port="/dev/ttyUSB1"); B.reset()
for d, nm in ((A, "A"), (B, "B")):
    load(d, "examples/apps/lora/lora1.fs"); load(d, "examples/apps/lora/lora_rx.fs")
    print(nm, "INIT ->", d.num("INIT .", 8.0), " here", d.num("HERE ."), "latest", d.num("LATEST ."))
B.cmd(": STAT NSSLO 192 >BYTE RD-BYTE NSSHI ;", 6.0, allow_error=True)
print("B: clear+SetRx ->", B.cmd("RC SR", 6.0, allow_error=True).strip()[-6:])
st = B.num("STAT .", 6.0); print("B chipmode after SetRx: %d (5 = RX)" % ((st >> 4) & 7))
print("B irq before A sends:", B.num("IQ .", 6.0))
print("A SEND ->", A.num("SEND .", 10.0))
time.sleep(0.6)
irq = B.num("IQ .", 6.0)
print("B irq after A sent    : 0x%04X  (bit1 RxDone %s, bit6 CrcErr %s)" % (irq, bool(irq & 2), bool(irq & 0x40)))
st = B.num("STAT .", 6.0); print("B chipmode now: %d" % ((st >> 4) & 7))
if irq & 2:
    print("B payload:", B.cmd("RL RB", 8.0, allow_error=True).strip()[-30:])
