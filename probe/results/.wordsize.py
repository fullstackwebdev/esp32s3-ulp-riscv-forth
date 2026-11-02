import sys, pathlib, re
sys.path.insert(0, "probe/repl/tools")
from devio import Dev
d = Dev(port="/dev/ttyUSB1"); d.reset()
h0, l0 = d.num("HERE ."), d.num("LATEST .")
print(f"boot: HERE {h0} LATEST {l0} free {l0-h0}")
rows = []
for path in ("examples/apps/lora/lora1.fs", "examples/apps/lora/lora_rx.fs"):
    pend, name = [], None
    for raw in pathlib.Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("\\"): continue
        m = re.match(r":\s+(\S+)", line)
        if m and not pend: name = m.group(1)
        if name:
            pend.append(line)
            if line.endswith(";"):
                hb, lb = d.num("HERE ."), d.num("LATEST .")
                for one in pend: d.cmd(one, 8.0, allow_error=True)
                ha, la = d.num("HERE ."), d.num("LATEST .")
                rows.append((name, ha - hb, lb - la))
                pend, name = [], None
            continue
        d.cmd(line, 8.0, allow_error=True)
print(f"{'word':10s} {'code':>5s} {'hdr':>4s} {'total':>6s}   group")
P = {"PIN!", "PIN@", "BITOUT", ">BYTE", "BITREAD", "RD-BYTE", "RD2", "NSSLO", "NSSHI",
     "BUSY-LOW", "INEN", "CLOCKLOW", "NSSPAD", "SCKPAD", "MOSIPAD", "NRSTPAD", "BUSYPAD",
     "PADINRD", "PADSETW", "PADCLRW", "TEST", "SETRX"}
for name, code, hdr in rows:
    grp = "primitive" if name in P else ("init" if name in ("INIT",) else
          ("tx" if name in ("SEND",) else "rx"))
    print(f"{name:10s} {code:5d} {hdr:4d} {code+hdr:6d}   {grp}")
tot = {}
for name, code, hdr in rows:
    grp = "primitive" if name in P else ("init" if name == "INIT" else ("tx" if name == "SEND" else "rx"))
    tot[grp] = tot.get(grp, 0) + code + hdr
print("group totals:", {k: v for k, v in sorted(tot.items())})
h1, l1 = d.num("HERE ."), d.num("LATEST .")
print(f"end : HERE {h1} LATEST {l1} free {l1-h1}")
