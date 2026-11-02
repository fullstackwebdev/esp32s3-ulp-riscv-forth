import sys, pathlib, re
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
for port in ("/dev/ttyUSB0", "/dev/ttyUSB1"):
    d = Dev(port=port); d.reset()
    load(d, "examples/apps/lora/lora1.fs"); load(d, "examples/apps/lora/lora_rx.fs")
    d.num("INIT .", 8.0)
    # ReadRegister 0x1D: opcode, addrHi, addrLo, then one dummy byte, then the data
    d.cmd(": RG NSSLO 29 >BYTE 8 >BYTE 128 >BYTE RD-BYTE DROP ;", 6.0, allow_error=True)
    rep = d.cmd("RG RD-BYTE . RD-BYTE . RD-BYTE . RD-BYTE . NSSHI", 6.0, allow_error=True)
    nums = re.findall(r"\d+", rep.split("\n")[1] if "\n" in rep else rep)
    print(f"{port}: RF_FREQ(0x0880) bytes {nums[:4]}   want [54, 65, 153, 153] = 0x36419999 = 868.1 MHz")
