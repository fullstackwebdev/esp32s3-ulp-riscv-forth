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

A = Dev(port="/dev/ttyUSB0"); A.reset()
load(A, "examples/apps/lora/lora1.fs"); load(A, "examples/apps/lora/lora_rx.fs")
print("A INIT ->", A.num("INIT .", 8.0))
# accept a 20-byte payload: PB pushes the 6 SetPacketParams bytes, the caller supplies opcode and framing
A.cmd(": PB >BYTE >BYTE >BYTE >BYTE >BYTE >BYTE ;", 6.0, allow_error=True)
A.cmd("NSSLO 140 0 8 0 20 1 0 PB NSSHI", 6.0, allow_error=True)
A.cmd("RC SR", 6.0, allow_error=True)
print("A listening (chipmode %d); B is running the C driver at 868.1 MHz, 20-byte frames every 5 s"
      % ((A.num("NSSLO 192 >BYTE RD-BYTE NSSHI .", 6.0) >> 4) & 7))
seen = []
for i in range(15):
    irq = A.num("IQ .", 6.0)
    if irq:
        seen.append(irq)
        print(f"  t+{i}s irq 0x{irq:04X} -> ", A.cmd("RL RB", 8.0, allow_error=True).strip()[-40:])
        A.cmd("RC SR", 6.0, allow_error=True)
    time.sleep(1.0)
print("irq words seen:", ["0x%04X" % s for s in seen] or "none")
