import sys, pathlib, re
sys.path.insert(0,"/home/user/research/esp32-rv32"); sys.path.insert(0,"tools")
import devio, cli
ROOT=pathlib.Path("/home/user/research/esp32-rv32")
DESC=int(sys.argv[1])
d=cli.connect("/dev/ttyACM1",1.0)
try:
    cli.library(d,ROOT)
    try:
        r=d.cmd(f"{DESC} SWITCH", timeout=6.0, allow_error=True)
        blocks=re.findall(r"from block (\d+)", r)
        print("RESULT desc=%d returned adopts=%s steps=%d done=%d" % (DESC, blocks, r.count("step"), r.count("phases done")))
        print("  NXT now: %d  PA now: %d" % (d.num("NXT @ ."), d.num("PA @ .")))
    except devio.Timeout:
        print("RESULT desc=%d HUNG inside SWITCH" % DESC)
finally:
    d.close()
