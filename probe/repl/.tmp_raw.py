import sys, pathlib
sys.path.insert(0,"/home/user/research/esp32-rv32"); sys.path.insert(0,"tools")
import devio, cli
ROOT=pathlib.Path("/home/user/research/esp32-rv32")
d=cli.connect("/dev/ttyACM1",1.0)
try:
    cli.library(d,ROOT)
    try:
        r=d.cmd("60 SWITCH", timeout=6.0, allow_error=True)
        print("LEN", len(r))
        print("TAIL:", repr(r[-400:]))
    except devio.Timeout as e:
        print("TIMEOUT:", str(e)[:400])
finally:
    d.close()
