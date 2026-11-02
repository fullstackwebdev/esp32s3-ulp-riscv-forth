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
print("both INIT done")
A.cmd("RC SR", 6.0, allow_error=True)        # A listens
print("A chipmode after SetRx:", (A.num("NSSLO 192 >BYTE RD-BYTE NSSHI .", 6.0) >> 4) & 7)
def sender():
    for i in range(6):
        B.num("SEND .", 10.0); time.sleep(0.35)
t = threading.Thread(target=sender); t.start()
vals = []
for i in range(20):
    vals.append(A.num("NSSLO 21 >BYTE RD-BYTE NSSHI .", 6.0)); time.sleep(0.12)
t.join()
print("A RSSI raw while B sends:", vals)
print("A irq now: 0x%04X (bit1 RxDone, bit6 CrcErr)" % A.num("IQ .", 6.0))
