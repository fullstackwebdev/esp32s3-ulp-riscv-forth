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
for port in ("/dev/ttyUSB0", "/dev/ttyUSB1"):
    d = Dev(port=port); d.reset()
    load(d, "examples/apps/lora/lora1.fs"); load(d, "examples/apps/lora/lora_rx.fs")
    d.num("INIT .", 8.0)
    # finite RX timeout: 0x00FFF0 ticks * 15.625 us = 63.75 ms. If the chip really enters RX it MUST set
    # IRQ bit 0x0200 (Timeout) shortly after. That needs no transmitter and no RF at all.
    print(port, "before:", "0x%04X" % d.num("IQ .", 6.0))
    d.cmd("RC", 5.0, allow_error=True)
    d.cmd("NSSLO 130 >BYTE 0 >BYTE 255 >BYTE 240 >BYTE NSSHI", 6.0, allow_error=True)
    st = d.num("NSSLO 192 >BYTE RD-BYTE NSSHI .", 6.0)
    time.sleep(0.30)
    irq = d.num("IQ .", 6.0)
    st2 = d.num("NSSLO 192 >BYTE RD-BYTE NSSHI .", 6.0)
    print(f"  status right after SetRx 0x{st:02X} (chipmode {(st>>4)&7})  "
          f"irq after 300 ms 0x{irq:04X} -> Timeout {'YES' if irq & 0x200 else 'NO'}  "
          f"status 0x{st2:02X} (chipmode {(st2>>4)&7})")
