import sys, os, time, select, pathlib, re
sys.path.insert(0,"/home/user/research/esp32-rv32"); sys.path.insert(0,"tools")
import cli
ROOT=pathlib.Path("/home/user/research/esp32-rv32")
d=cli.connect("/dev/ttyACM1",1.0)
try:
    cli.library(d,ROOT); d.cmd("RW")
    os.write(d.fd, b"60 SWITCH\r")
    time.sleep(1.0)
    try:
        r = d.cmd("#u", timeout=5.0)          # the HP console answers even while the ULP spins
        for ln in r.splitlines():
            if "serviced" in ln or "ulp blk" in ln or "V_STATE" in ln: print("  ", ln.strip()[:150])
    except Exception as e:
        print("  #u failed:", type(e).__name__)
finally: d.close()
