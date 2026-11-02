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
print("INIT ->", A.num("INIT .", 8.0))
def probe(tag):
    e = A.cmd("NSSLO 23 >BYTE RD-BYTE RD-BYTE NSSHI . .", 6.0, allow_error=True)
    s = A.num("NSSLO 192 >BYTE RD-BYTE NSSHI .", 6.0)
    print(f"{tag:16s} devErr bytes {' '.join(e.split()[-4:])}  status 0x{s:02X} chipmode {(s>>4)&7}")
probe("after INIT")
print("SEND ->", A.num("SEND .", 10.0))
probe("after SEND")
time.sleep(0.5)
probe("0.5 s later")
# also read back the frequency the chip holds (GetRfFrequency 0x15? no - 0x15 is GetRssiInst); try packet type
print("packetType:", A.cmd("NSSLO 17 >BYTE RD-BYTE NSSHI .", 6.0, allow_error=True).split()[-3:])
