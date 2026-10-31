import os,re,select,subprocess,termios,time,pathlib
PORT="/dev/ttyACM1"
def reset():
    subprocess.run(["python3","-m","esptool","--port",PORT,"--after","hard_reset","chip_id"],capture_output=True); time.sleep(2.0)
fd=None
def openp():
    global fd
    fd=os.open(PORT,os.O_RDWR|os.O_NOCTTY)
    a=termios.tcgetattr(fd);a[0]=0;a[1]=0;a[2]=termios.CS8|termios.CREAD|termios.CLOCAL;a[3]=0
    a[4]=a[5]=termios.B115200;a[6][termios.VMIN]=0;a[6][termios.VTIME]=0
    termios.tcsetattr(fd,termios.TCSANOW,a)
def drain(q=0.45,cap=30):
    b=b"";end=time.time()+cap;last=time.time()
    while time.time()<end:
        r,_,_=select.select([fd],[],[],0.05)
        if r:
            c=os.read(fd,4096)
            if c: b+=c;last=time.time()
        elif time.time()-last>q: break
    return b.decode("ascii","replace")
def line(s,q=0.45,cap=30):
    os.write(fd,s.encode()+b"\r"); return drain(q,cap)
def flat(o): return " | ".join(x.strip() for x in o.split("\n") if x.strip())
def nums(o): return [int(x) for x in re.findall(r"-?\d+",o)]
def seed(blk,txt):
    for _ in range(3):
        o=line(f"#b {blk} {txt.encode().hex()}",0.25,3.0)
        if f"seed: block {blk} <-" in o: return True
    return False
def strip_all(t):
    t=re.sub(r"\\.*","",t); t=re.sub(r"\([^)]*\)","",t); return " ".join(t.split())
def chunk(t,size=128):
    out=[];i=0
    while i<len(t):
        e=min(i+size,len(t))
        if e<len(t):
            c=t.rfind(" ",i+1,e)
            if c>i: e=c+1
        out.append(t[i:e]); i=e
    return out
# ---------- P2: verify the instrument on known content
reset(); openp(); time.sleep(1.2); drain(0.8)
line("0 BLOCK CONSTANT W")
line(": BLKBLANK 0 BEGIN DUP 128 < WHILE 32 OVER W + C! 1 + REPEAT DROP ;")
line("0 BLOCK DROP BLKBLANK UPDATE SAVE DROP")
line("CREATE ix 0 ,"); line("CREATE ib 0 ,")
print("S16 define ->", flat(line(": S16 ib ! 0 ix ! 0 BEGIN ix @ 16 < WHILE ib @ ix @ + C@ + ix @ 1 + ix ! REPEAT ;",0.7)))
line("0 BLOCK")
print("P2 block 0 (128 spaces, expect 4096):", flat(line("S16 .",0.6)))
line("1 BLOCK")
print("P2 block 1 raw (expect something):", flat(line("S16 .",0.6)))
seed(1,"A"*128)
line("1 BLOCK")
print("P2 block 1 (128 'A', expect 8320):", flat(line("S16 .",0.6)))
os.close(fd)
# ---------- P2b: transport of the 7 phase blocks, BEFORE any SEAL/OVL/LOAD
reset(); openp(); time.sleep(1.2); drain(0.8)
ch=chunk(strip_all(pathlib.Path("tests/ph1.fsx").read_text()))
for k,c in enumerate(ch):
    if not seed(8+k,c): print(f"  seed {8+k} FAILED")
line("CREATE ix 0 ,"); line("CREATE ib 0 ,")
line(": S16 ib ! 0 ix ! 0 BEGIN ix @ 16 < WHILE ib @ ix @ + C@ + ix @ 1 + ix ! REPEAT ;",0.7)
bad=0
for k,c in enumerate(ch):
    want=[sum(ord(x) for x in c.ljust(128," ")[i*16:(i+1)*16]) for i in range(8)]
    dev=[]
    for seg in range(8):
        line(f"{8+k} BLOCK {seg*16} +")
        o=line("S16 .",0.6); n=nums(o); dev.append(n[-1] if n else None)
    mism=[i for i,(d,w) in enumerate(zip(dev,want)) if d!=w]
    bad+=len(mism)
    print(f"  P2b block {8+k}: {'8/8 segments MATCH' if not mism else f'MISMATCH {mism} dev={[dev[i] for i in mism]} src={[want[i] for i in mism]}'}")
print(f"  P2b verdict: {bad} bad segment(s) of {len(ch)*8}")
os.close(fd)
# ---------- P2c-f: colon body spanning a block boundary
reset(); openp(); time.sleep(1.2); drain(0.8)
seed(8,": SPAN1 41 ."); seed(9,". ;")
line("SEAL"); print("P2c-f sealed:", flat(line("LATEST . HERE .")))
line("2 OVL",0.8)
print("  8 LOAD ->", flat(line("8 LOAD",1.2)))
print("  9 LOAD ->", flat(line("9 LOAD",1.2)))
print("  LATEST/HERE ->", flat(line("LATEST . HERE .")))
print("  ' SPAN1 ->", flat(line("' SPAN1 .")))
print("  SPAN1 run ->", flat(line("SPAN1",1.0)))
os.close(fd)
# ---------- P3: the real phase, per block, with name lookups
reset(); openp(); time.sleep(1.2); drain(0.8)
for k,c in enumerate(ch):
    seed(8+k,c)
line("SEAL"); line("2 OVL",0.8)
names={8:"DATABLK",9:"TAB",10:"S2",14:"S1"}
for k in range(len(ch)):
    o=flat(line(f"{8+k} LOAD",1.2))
    lh=flat(line("LATEST . HERE .",0.5))
    nm=names.get(8+k)
    look=flat(line("' "+nm+" .",0.5)) if nm else ""
    print(f"  P3 block {8+k}: {o}  | {lh}  | ' {nm} -> {look}")
os.close(fd)
