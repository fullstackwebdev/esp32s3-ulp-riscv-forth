import sys, pathlib, re, time, threading
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
B = Dev(port="/dev/ttyUSB1"); B.reset()
for d in (A, B):
    load(d, "examples/apps/lora/lora1.fs"); load(d, "examples/apps/lora/lora_rx.fs")
    d.num("INIT .", 8.0)
# enable EVERY irq source (mask 0xFFFF, no DIO routing) - INIT only enables Timeout|TxDone
B.cmd(": PB >BYTE >BYTE >BYTE >BYTE >BYTE >BYTE ;", 6.0, allow_error=True)
B.cmd("NSSLO 8 255 255 255 255 PB 0 0 NSSHI", 6.0, allow_error=True)
B.cmd("RC SR", 6.0, allow_error=True)
print("B listening with irqMask 0xFFFF, chipmode", (B.num("NSSLO 192 >BYTE RD-BYTE NSSHI .", 6.0) >> 4) & 7)
def send():
    for i in range(4):
        A.num("SEND .", 10.0); time.sleep(0.5)
t = threading.Thread(target=send); t.start()
time.sleep(3.0)
t.join()
irq = B.num("IQ .", 6.0)
print("B irq after 4 of A's frames: 0x%04X (RxDone bit %s, Preamble %s, Header %s, CrcErr %s, Timeout %s)"
      % (irq, bool(irq & 2), bool(irq & 4), bool(irq & 0x10), bool(irq & 0x40), bool(irq & 0x200)))
print("B GetRxBufferStatus (len off):", B.cmd("RL", 6.0, allow_error=True).strip().replace("\r\n", " ")[-12:])
print("B chipmode now:", (B.num("NSSLO 192 >BYTE RD-BYTE NSSHI .", 6.0) >> 4) & 7)
