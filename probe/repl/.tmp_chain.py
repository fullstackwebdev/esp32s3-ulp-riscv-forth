import sys, pathlib
sys.path.insert(0,"/home/user/research/esp32-rv32"); sys.path.insert(0,"tools")
import cli
ROOT=pathlib.Path("/home/user/research/esp32-rv32")
d=cli.connect("/dev/ttyACM1",1.0)
def q(s,t=6.0):
    try:
        r=d.cmd(s,timeout=t,allow_error=True)
        return repr(r)[:300]
    except Exception as e:
        return f"<{type(e).__name__}>"
try:
    cli.library(d,ROOT)
    print("chain :", q("60 SWITCH", 15.0))
    print("NXT   :", q("NXT @ ."), " PA:", q("PA @ ."))
finally:
    d.close()
