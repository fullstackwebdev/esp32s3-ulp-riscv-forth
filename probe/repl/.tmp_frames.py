import os,sys,pty,time,select,subprocess,signal
ROOT="/home/user/research/esp32-rv32"
m,s=pty.openpty()
p=subprocess.Popen([sys.executable,ROOT+"/cli.py","--library","--term"],cwd=ROOT,stdin=s,stdout=s,stderr=s,close_fds=True)
os.close(s)
def frame(cap=20.0):
    b=b"";e=time.time()+cap
    while time.time()<e and b"\x00" not in b:
        r,_,_=select.select([m],[],[],0.05)
        if r:
            try: c=os.read(m,65536)
            except OSError: break
            if not c: break
            b+=c
    return b
try:
    f1=frame(40); print("menu frame:", len(f1), repr(f1[:80]))
    os.write(m,b"j"); f2=frame(); print("after j  :", len(f2))
    os.write(m,b"k"); f3=frame(); print("after k  :", len(f3))
    os.write(m,b"\r"); f4=frame(); print("after CR :", len(f4), repr(f4[:160]))
    f5=frame(3); print("next     :", len(f5), repr(f5[:120]))
finally:
    p.send_signal(signal.SIGINT)
    try: p.wait(5)
    except Exception: p.kill()
    os.close(m)
