import sys, pathlib
sys.path.insert(0,"/home/user/research/esp32-rv32"); sys.path.insert(0,"tools")
import cli
ROOT=pathlib.Path("/home/user/research/esp32-rv32")
d=cli.connect("/dev/ttyACM1",1.0)
def n(s,t=5.0):
    try: return d.num(s, timeout=t)
    except Exception as e: return f"<{type(e).__name__}>"
try:
    cli.library(d,ROOT)
    for w in ("bh .", "bl .", "SEL .", "NXT .", "PA .", "HERE .", "LATEST ."):
        print(f"  {w:10} -> {n(w)}")
    print("  NXT @ ->", n("NXT @ ."), "  PA @ ->", n("PA @ ."))
finally:
    d.close()
