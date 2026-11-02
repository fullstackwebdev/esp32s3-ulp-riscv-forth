import sys, pathlib, re
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
d = Dev(port="/dev/ttyUSB1"); d.reset()
load(d, "examples/apps/lora/lora1.fs"); load(d, "examples/apps/lora/lora_rx.fs")
d.cmd(": STAT NSSLO 192 >BYTE RD-BYTE NSSHI ;", 6.0, allow_error=True)
print("INIT ->", d.num("INIT .", 8.0))
def trial(name, line):
    d.cmd("CLRIQX", 5.0, allow_error=True)
    d.cmd(line, 6.0, allow_error=True)
    st = d.num("STAT .", 6.0); irq = d.num("IRQW .", 6.0)
    print(f"{name:34s} status 0x{st:02X} chipmode {(st>>4)&7}  irq 0x{irq:04X}")
trial("SetRx 0xFFFFFF continuous", "NSSLO 130 >BYTE 255 >BYTE 255 >BYTE 255 >BYTE NSSHI 60 MS")
trial("SetRx 0x000000 single", "NSSLO 130 >BYTE 0 >BYTE 0 >BYTE 0 >BYTE NSSHI 60 MS")
trial("SetRx 0x000100 (~16 ms)", "NSSLO 130 >BYTE 0 >BYTE 1 >BYTE 0 >BYTE NSSHI 60 MS")
trial("standby then SetRx", "NSSLO 128 >BYTE 0 >BYTE NSSHI 5 MS NSSLO 130 >BYTE 255 >BYTE 255 >BYTE 255 >BYTE NSSHI 60 MS")
trial("PKRX then SetRx", "PKRX NSSLO 130 >BYTE 255 >BYTE 255 >BYTE 255 >BYTE NSSHI 60 MS")
print("busy pin now:", d.num("BUSYPAD PIN@ .", 5.0))
