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
load(d, "examples/apps/lora/lora1.fs"); load(d, "examples/apps/lora/lora_rx.fs")
print("INIT ->", d.num("INIT .", 8.0))
d.cmd(": STAT NSSLO 192 >BYTE RD-BYTE NSSHI ;", 6.0, allow_error=True)
print("stat cmd defined:", bool(d.nums(d.cmd("' STAT .", 5.0, allow_error=True))))
print("status after INIT      : 0x%02X (chipmode %d)" % (lambda s: (s, (s >> 4) & 7))(d.num("STAT .", 6.0)))
d.cmd("CLRIQX", 6.0, allow_error=True)
print("irq right after clear  :", d.num("IRQW .", 6.0))
print("status after clear     : 0x%02X (chipmode %d)" % (lambda s: (s, (s >> 4) & 7))(d.num("STAT .", 6.0)))
d.cmd("PKRX", 6.0, allow_error=True)
d.cmd("SETRX", 6.0, allow_error=True)
print("status after SETRX     : 0x%02X (chipmode %d, 5 = RX)" % (lambda s: (s, (s >> 4) & 7))(d.num("STAT .", 6.0)))
print("irq after SETRX        :", d.num("IRQW .", 6.0))
print("irq after 250 ms       :", d.num("250 MS IRQW .", 8.0))
print("status at end          : 0x%02X (chipmode %d)" % (lambda s: (s, (s >> 4) & 7))(d.num("STAT .", 6.0)))
