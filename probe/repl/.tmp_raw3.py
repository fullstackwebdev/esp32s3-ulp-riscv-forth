import sys, os, time, select, pathlib, re
sys.path.insert(0,"/home/user/research/esp32-rv32"); sys.path.insert(0,"tools")
import cli
ROOT=pathlib.Path("/home/user/research/esp32-rv32")
d=cli.connect("/dev/ttyACM1",1.0)
try:
    cli.library(d,ROOT)
    d.cmd("RW")
    os.write(d.fd, b"60 SWITCH\r")
    buf=b""; end=time.time()+3.0
    while time.time()<end:
        r,_,_=select.select([d.fd],[],[],0.05)
        if r:
            try: buf += os.read(d.fd, 8192)
            except OSError: break
    t=buf.decode("latin-1")
    print("adopts :", re.findall(r"from block (\d+)", t))
    print("REFUSED:", re.findall(r"REFUSED[^\r\n]{0,90}", t)[:2])
    print("steps  :", t.count("step"), " done:", t.count("phases done"))
finally: d.close()
