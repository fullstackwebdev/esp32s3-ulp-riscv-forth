import pathlib, re, subprocess, sys
GEN = pathlib.Path("probe/results/gen_aes.py")
OUT = "examples/apps/lora/lora_aes.fs"
for it in range(15):
    subprocess.run([sys.executable, str(GEN)], check=True, capture_output=True)
    r = subprocess.run([sys.executable, "probe/repl/tools/namecheck.py", "--port", "/dev/ttyUSB1", OUT],
                       capture_output=True, text=True)
    taken = re.findall(r"`(\w+)` is already on the machine", r.stdout)
    if not taken:
        print(f"board says every name is free after {it} round(s)")
        break
    t = GEN.read_text()
    for n in sorted(set(taken)):
        new = (n + "X") if len(n) < 8 else n[:7] + "X"
        t = re.sub(rf"\b{re.escape(n)}\b", new, t)
        print(f"  {n} -> {new}")
    GEN.write_text(t)
subprocess.run([sys.executable, str(GEN)])
