import sys, pathlib, re, time, threading
sys.path.insert(0, "probe/repl/tools")
from devio import Dev
def load(dev, path):
    pend, name = [], None
    for raw in pathlib.Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("\\"): continue
        if name is None and re.match(r":\s+(\S+)", line): name = re.match(r":\s+(\S+)", line).group(1)
        if name:
            pend.append(line)
            if line.endswith(";"):
                for one in pend: dev.cmd(one, 8.0, allow_error=True)
                ped = dev.nums(dev.cmd("' " + name + " .", 5.0, allow_error=True))
                if not ped: print(f"   {name} ABSENT")
                pend, name = [], None
            continue
        dev.cmd(line, 8.0, allow_error=True)
B = Dev(port="/dev/ttyUSB1"); B.reset()
h0, l0 = B.num("HERE ."), B.num("LATEST .")
print(f"B boot: HERE {h0} LATEST {l0} free {l0-h0}")
load(B, "examples/apps/lora/lorainit.fs")
h1, l1 = B.num("HERE ."), B.num("LATEST .")
print(f"INIT phase file: code {h1-h0} B, headers {l0-l1} B, total {h1-h0+l0-l1} B, free {l1-h1}")
print("RADIO-INIT ->", B.num("RADIO-INIT .", 25.0))
print("STAT       -> 0x%02X (chipmode %d, want 2 = STDBY_RC)" % (lambda s: (s, (s>>4)&7))(B.num("STAT .", 6.0)))
f = B.cmd("RDFREQ . . . .", 8.0, allow_error=True)
print("RDFREQ     ->", " ".join(f.split()[-6:]), " (want 54 65 153 153 = 0x36419999 = 868.1 MHz)")
# and can it still hear? load the receive words on top and listen
load(B, "examples/apps/lora/lora_rx.fs")
B.cmd("RC SR", 6.0, allow_error=True)
print("after SR: STAT -> 0x%02X (chipmode %d, want 5 = RX)" % (lambda s: (s, (s>>4)&7))(B.num("STAT .", 6.0)))
A = Dev(port="/dev/ttyUSB0"); A.reset()
load(A, "examples/apps/lora/lora1.fs")
print("A INIT ->", A.num("INIT .", 8.0))
def send():
    for i in range(3):
        A.num("SEND .", 10.0); time.sleep(0.4)
t = threading.Thread(target=send); t.start(); t.join(); time.sleep(0.4)
irq = B.num("IQ .", 6.0)
print("B irq after A's frames: 0x%04X  RxDone=%s  payload:" % (irq, bool(irq & 2)),
      B.cmd("RL RB", 8.0, allow_error=True).strip().replace("\r\n", " ")[-30:])
