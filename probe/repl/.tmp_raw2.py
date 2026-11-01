import sys, pathlib, re
sys.path.insert(0,"/home/user/research/esp32-rv32"); sys.path.insert(0,"tools")
import devio, cli
ROOT=pathlib.Path("/home/user/research/esp32-rv32")
d=cli.connect("/dev/ttyACM1",1.0)
try:
    cli.library(d,ROOT)
    try:
        r=d.cmd("60 SWITCH", timeout=8.0, allow_error=True, markers=(" ok",))
        print("FINISHED adopts=%s steps=%d done=%d" % (re.findall(r"from block (\d+)", r), r.count("step"), r.count("phases done")))
    except devio.Timeout:
        print("HUNG")
finally:
    d.close()
