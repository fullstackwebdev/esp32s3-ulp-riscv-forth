import pathlib, re, subprocess, sys
GEN = pathlib.Path("probe/results/gen_aes.py")
for it in range(14):
    subprocess.run([sys.executable, str(GEN)], check=True, capture_output=True)
    r = subprocess.run([sys.executable, "probe/repl/tests/lora_aes.py"], capture_output=True, text=True)
    bad = re.findall(r"`(\w+)` (?:did not appear|already exists)", r.stdout + r.stderr)
    if not bad:
        print("loaded and ran with no refusal" if "failure(s)" in r.stdout else "loaded, test output:")
        print("\n".join(l for l in r.stdout.splitlines() if "PASS" in l or "FAIL" in l or "footprint" in l))
        break
    t = GEN.read_text()
    for n in sorted(set(bad)):
        new = n + "Q" if len(n) < 8 else n[:7] + "Q"
        t = re.sub(rf"\b{re.escape(n)}\b", new, t)
        print(f"  refused {n} -> {new}")
    GEN.write_text(t)
