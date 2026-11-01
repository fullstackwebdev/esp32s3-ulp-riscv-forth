import sys, pathlib
sys.path.insert(0,"/home/user/research/esp32-rv32"); sys.path.insert(0,"tools")
import devio, cli
ROOT=pathlib.Path("/home/user/research/esp32-rv32")
d=cli.connect("/dev/ttyACM1",1.0)
def run(desc, t=4.0):
    try:
        r=d.cmd(f"{desc} SWITCH", timeout=t, allow_error=True)
        import re
        return "ok  adopts=" + str(re.findall(r"from block (\d+)", r)) + f" steps={r.count('step')}"
    except devio.Timeout:
        return "HUNG (still inside SWITCH)"
try:
    cli.library(d,ROOT)
    for desc, label in ((66,"phase 4 only"), (64,"phases 3+4"), (62,"phases 2..4"), (60,"all four")):
        print(f"{label:14} from block {desc}: {run(desc)}")
        d.reset(settle=0.3); cli.library(d,ROOT)
finally:
    d.close()
