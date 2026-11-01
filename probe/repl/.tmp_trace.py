import os,sys,pty,time,select,subprocess,signal,re
ROOT="/home/user/research/esp32-rv32"
m,s=pty.openpty()
p=subprocess.Popen([sys.executable,ROOT+"/cli.py","--library","--term"],cwd=ROOT,stdin=s,stdout=s,stderr=s,close_fds=True)
os.close(s)
def dwell(cap):
    b=b"";e=time.time()+cap
    while time.time()<e:
        r,_,_=select.select([m],[],[],0.05)
        if r:
            try: c=os.read(m,65536)
            except OSError: break
            if not c: break
            b+=c
    return b
try:
    dwell(40); os.write(m,b"j"); dwell(0.4); os.write(m,b"j"); dwell(0.4)
    os.write(m,b"\r"); out=dwell(6.0)
    t=out.decode("latin-1").replace("\x00","")
    print("adopts :", re.findall(r"from block (\d+)", t))
    print("step   :", t.count("step"), " phase4:", t.count("phases done"))
    print("refused:", re.findall(r"REFUSED[^\r\n]{0,60}", t)[:3])
    print("err    :", re.findall(r"ERR_[A-Z]+", t)[:5])
finally:
    p.send_signal(signal.SIGINT)
    try: p.wait(6)
    except Exception: p.kill()
    os.close(m)
