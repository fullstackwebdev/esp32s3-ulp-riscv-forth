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
# B listens continuously; GetRssiInst is opcode 0x15 -> one byte, RSSI = -value/2 dBm
B.cmd("RC SR", 6.0, allow_error=True)
def sender():
    for i in range(6):
        A.num("SEND .", 10.0)
        time.sleep(0.35)
t = threading.Thread(target=sender); t.start()
vals = []
for i in range(24):
    vals.append(B.num("NSSLO 21 >BYTE RD-BYTE NSSHI .", 6.0))
    time.sleep(0.1)
t.join()
print("RSSI raw bytes (0 = no signal, 255 = -127 dBm):", vals)
print("min/max:", min(vals), max(vals), "-> %.1f .. %.1f dBm" % (-max(vals)/2, -min(vals)/2))
print("B irq after:", "0x%04X" % B.num("IQ .", 6.0))
