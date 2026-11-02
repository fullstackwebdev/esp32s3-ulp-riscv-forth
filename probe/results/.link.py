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
B.cmd("RC SR", 6.0, allow_error=True)                  # continuous RX, no window
def send():
    for i in range(4):
        A.num("SEND .", 10.0); time.sleep(0.4)
t = threading.Thread(target=send); t.start(); t.join()
time.sleep(0.5)
irq = B.num("IQ .", 6.0)
print("B irq after 4 frames (continuous RX): 0x%04X  RxDone=%s" % (irq, bool(irq & 2)))
if irq & 2:
    print("payload:", B.cmd("RL RB", 8.0, allow_error=True).strip().replace("\r\n", " ")[-40:])
