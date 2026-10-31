import os,re,select,subprocess,termios,time,pathlib
PORT="/dev/ttyACM1"
def reset():
    subprocess.run(["python3","-m","esptool","--port",PORT,"--after","hard_reset","chip_id"],
                   capture_output=True); time.sleep(2.0)
def openp():
    fd=os.open(PORT,os.O_RDWR|os.O_NOCTTY)
    a=termios.tcgetattr(fd);a[0]=0;a[1]=0;a[2]=termios.CS8|termios.CREAD|termios.CLOCAL;a[3]=0
    a[4]=a[5]=termios.B115200;a[6][termios.VMIN]=0;a[6][termios.VTIME]=0
    termios.tcsetattr(fd,termios.TCSANOW,a); return fd
def drain(fd,q=0.45,cap=25):
    b=b"";end=time.time()+cap;last=time.time()
    while time.time()<end:
        r,_,_=select.select([fd],[],[],0.05)
        if r:
            c=os.read(fd,4096)
            if c: b+=c;last=time.time()
        elif time.time()-last>q: break
    return b.decode("ascii","replace")
def line(fd,s,q=0.45,cap=25):
    os.write(fd,s.encode()+b"\r"); return drain(fd,q,cap)
def flat(o): return " | ".join(x.strip() for x in o.split("\n") if x.strip())
def seed(fd,blk,txt):
    for _ in range(3):
        o=line(fd,f"#b {blk} {txt.encode().hex()}",0.25,3.0)
        if f"seed: block {blk} <-" in o: return True
    return False
def session(name, blocks, loads, lookups):
    reset(); fd=openp(); time.sleep(1.2); drain(fd,0.8)
    for blk,txt in blocks:
        if not seed(fd,blk,txt): print(f"  {name}: SEED FAILED block {blk}"); os.close(fd); return
    s=line(fd,"SEAL"); h=flat(line(fd,"LATEST . HERE ."))
    print(f"== {name}: sealed LATEST/HERE = {h}")
    line(fd,"2 OVL",0.8)
    for blk in loads:
        print(f"   {blk} LOAD -> {flat(line(fd,f'{blk} LOAD',1.3))}   LATEST/HERE {flat(line(fd,'LATEST . HERE .',0.5))}")
    for nm in lookups:
        cmd = "' " + nm + " ."
        print("   ' " + nm + " -> " + flat(line(fd, cmd, 0.5)))
    os.close(fd)
# --- P2c-a: one definition, block padded to full length by the seeder
session("P2c-a", [(8,": ZZ 42 . ;")], [8], ["ZZ"])
# --- P2c-b: CONSTANT
session("P2c-b", [(8,"4 CONSTANT QP")], [8], ["QP"])
# --- P2c-c: 128 bytes ending on a token, no trailing space
base=": ZC 42 . ;"; pad=" "* (128-len(base)-2); txt=base+pad+"ZC"
print(f"   (P2c-c text length = {len(txt)})")
session("P2c-c", [(8,txt)], [8], ["ZC"])
# --- P2c-d: block ends on a bare name with no body
session("P2c-d", [(8,"CREATE ZT")], [8], ["ZT"])
# --- P2c-e: 7 blocks, ONE definition each
session("P2c-e", [(8+k, f": E{k+1} {k+1} . ;") for k in range(7)], list(range(8,15)), ["E1","E7"])
