import pathlib, re, subprocess, sys
GEN = pathlib.Path("probe/results/gen_aes.py")
OUT = pathlib.Path("examples/apps/lora/lora_aes.fs")
OTHERS = ["examples/apps/lora/lorainit.fs", "examples/apps/lora/lora_rx.fs",
          "examples/apps/lora/lora1.fs", str(OUT)]
for it in range(12):
    subprocess.run([sys.executable, str(GEN)], check=True, capture_output=True)
    r = subprocess.run([sys.executable, "probe/repl/tools/hashcheck.py"] + OTHERS,
                       capture_output=True, text=True)
    if r.returncode == 0:
        print(f"clean after {it} rename round(s)")
        break
    names = set(re.findall(r"R25 hash: `(\w+)`", r.stdout))
    # only rename names that belong to THIS file (a resident name cannot be renamed)
    mine = set(re.findall(r"^:\s+(\w+)", OUT.read_text(), re.M)) | set(re.findall(r"^CREATE\s+(\w+)", OUT.read_text(), re.M))
    todo = names & mine
    if not todo:
        print("collisions left but not mine:", sorted(names)); break
    t = GEN.read_text()
    for n in sorted(todo):
        new = n + "Z" if len(n) < 9 else n[:8] + "Z"
        t = re.sub(rf"\b{re.escape(n)}\b", new, t)
        print(f"  {n} -> {new}")
    GEN.write_text(t)
print("final sizes:")
subprocess.run([sys.executable, str(GEN)])
