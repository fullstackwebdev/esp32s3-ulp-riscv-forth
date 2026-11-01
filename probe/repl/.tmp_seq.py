import sys, pathlib
sys.path.insert(0,"/home/user/research/esp32-rv32"); sys.path.insert(0,"tools")
import cli
ROOT=pathlib.Path("/home/user/research/esp32-rv32")
d=cli.connect("/dev/ttyACM1",1.0)
def q(s,t=5.0):
    try: return repr(d.cmd(s,timeout=t,allow_error=True,markers=(" ok","?",)))[:170]
    except Exception as e: return "<%s>" % type(e).__name__
try:
    cli.library(d,ROOT)
    print("1 RW        ", q("RW"))
    print("2 adopt 64  ", q("64 3 BLKXFER SWAP . ."))
    print("3 NXT       ", q("NXT @ ."))
    print("4 run 64    ", q("64 3 BLKXFER DROP @ EXECUTE", 6.0)[:90])
    print("5 NXT       ", q("NXT @ ."))
    print("6 RW        ", q("RW"))
    print("7 adopt 66  ", q("66 3 BLKXFER SWAP . ."))
    print("8 run 66    ", q("66 3 BLKXFER DROP @ EXECUTE", 6.0)[:90])
finally: d.close()
