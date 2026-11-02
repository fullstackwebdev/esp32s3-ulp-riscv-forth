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
print("B INIT ->", B.num("INIT .", 8.0))
B.cmd(": PB >BYTE >BYTE >BYTE >BYTE >BYTE >BYTE ;", 6.0, allow_error=True)
B.cmd("NSSLO 140 0 8 0 20 1 0 PB NSSHI", 6.0, allow_error=True)
B.cmd("RC SR", 6.0, allow_error=True)
print("B listening (chipmode %d) while A transmits C-driver 20 B frames every 5 s"
      % ((B.num("NSSLO 192 >BYTE RD-BYTE NSSHI .", 6.0) >> 4) & 7))
hits = []
for i in range(20):
    irq = B.num("IQ .", 6.0)
    if irq:
        hits.append(irq)
        print(f"  t+{i}s irq 0x{irq:04X} payload:", B.cmd("RL RB", 8.0, allow_error=True).strip()[-44:])
        B.cmd("RC SR", 6.0, allow_error=True)
    time.sleep(1.0)
print("irqs:", ["0x%04X" % h for h in hits] or "none")
