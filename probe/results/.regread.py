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
# ReadRegister(0x1D) addr 0x0880 = RF_FREQ (4 bytes): opcode, aHi, aLo, dummy, then data
rd = "NSSLO 29 >BYTE 8 >BYTE 128 >BYTE RD-BYTE DROP RD-BYTE . RD-BYTE . RD-BYTE . RD-BYTE . NSSHI"
print("A RF_FREQ reg:", A.cmd(rd, 8.0, allow_error=True).strip().replace("\r\n", " ")[-26:])
print("B RF_FREQ reg:", B.cmd(rd, 8.0, allow_error=True).strip().replace("\r\n", " ")[-26:])
print("(0x36419999 = 868.1 MHz = 54 65 153 153)")

# Now: does the receiver hear anything when A sends in a tight loop, with the RF switch forced off?
A.cmd(": TXL NSSLO 131 >BYTE 15 >BYTE 0 >BYTE 0 >BYTE NSSHI ;", 6.0, allow_error=True)
A.cmd(": LOOPX 20 BEGIN 1- DUP 0= IF DROP EXIT THEN TXL 200 MS REPEAT ;", 6.0, allow_error=True)
B.cmd("NSSLO 157 >BYTE 0 >BYTE NSSHI", 6.0, allow_error=True)   # DIO2 RF switch OFF
B.cmd("RC SR", 6.0, allow_error=True)
t = threading.Thread(target=lambda: A.cmd("LOOPX", 25.0, allow_error=True)); t.start()
vals = []
for i in range(30):
    vals.append(B.num("NSSLO 21 >BYTE RD-BYTE NSSHI .", 5.0)); time.sleep(0.1)
t.join()
print("B RSSI with switch OFF, A transmitting continuously:", sorted(set(vals)))
print("B irq:", "0x%04X" % B.num("IQ .", 6.0))
