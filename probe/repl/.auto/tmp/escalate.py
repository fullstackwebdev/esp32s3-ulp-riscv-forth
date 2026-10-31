import os,re,select,subprocess,termios,time,pathlib,sys
sys.path.insert(0,"tools")
from fsplit import split_defs
PORT="/dev/ttyACM1"
subprocess.run(["python3","-m","esptool","--port",PORT,"--after","hard_reset","chip_id"],capture_output=True); time.sleep(2)
fd=os.open(PORT,os.O_RDWR|os.O_NOCTTY)
a=termios.tcgetattr(fd);a[0]=0;a[1]=0;a[2]=termios.CS8|termios.CREAD|termios.CLOCAL;a[3]=0
a[4]=a[5]=termios.B115200;a[6][termios.VMIN]=0;a[6][termios.VTIME]=0
termios.tcsetattr(fd,termios.TCSANOW,a)
def drain(q=0.5,cap=40):
    b=b"";end=time.time()+cap;last=time.time()
    while time.time()<end:
        r,_,_=select.select([fd],[],[],0.05)
        if r:
            c=os.read(fd,4096)
            if c: b+=c;last=time.time()
        elif time.time()-last>q: break
    return b.decode("ascii","replace")
def line(s,q=0.5,cap=40):
    os.write(fd,s.encode()+b"\r"); return drain(q,cap)
def flat(o): return " | ".join(x.strip() for x in o.split("\n") if x.strip())
def nums(o): return [int(x) for x in re.findall(r"-?\d+",o)]
def seed(blk,txt):
    for _ in range(4):
        o=line(f"#b {blk} {txt.encode().hex()}",0.25,3.0)
        if f"seed: block {blk} <-" in o: return True
    return False
src=re.sub(r"\\.*","",pathlib.Path("tests/ph1.fsx").read_text())
src=" ".join(re.sub(r"\([^)]*\)","",src).split())
ch=split_defs(src,128); per=len(ch)
time.sleep(1.2); drain(0.8)
line("0 BLOCK CONSTANT W"); line(": BLKBLANK 0 BEGIN DUP 128 < WHILE 32 OVER W + C! 1 + REPEAT DROP ;")
line("2 BLOCK DROP BLKBLANK UPDATE SAVE DROP"); line("SEAL")
sealed=nums(line("HERE .",0.6))[-1]
print(f"{per} blocks/phase, sealed HERE={sealed}, store holds {128//per} phases")
high=0; total=0; seeded=0
for p in range(128//per):
    base=8+p*per
    if base+per>128: print(f"  stop: phase {p+1} needs blocks {base}..{base+per-1} past the store"); break
    ok=True
    for k,c in enumerate(ch):
        if not seed(base+k,c): print(f"  stop: seed of block {base+k} not acknowledged"); ok=False; break
        seeded+=1
    if not ok: break
    line("2 OVL",0.9)
    bad=None
    for k in range(per):
        out=flat(line(f"{base+k} LOAD",1.3))
        if "?" in out.replace("ok","").replace("LOAD","").replace(str(base+k),""):
            bad=(base+k,out); break
    if bad: print(f"  stop: block {bad[0]} -> {bad[1]!r}"); break
    h=nums(line("HERE .",0.6))[-1]
    size=h-sealed
    if not (400 <= size <= 700):
        print(f"  stop: phase {p+1} compiled {size} B, expected ~516 (partial assembly)"); break
    total+=size; high=p+1
    print(f"  phase {p+1:2d}: {size:4d} B compiled  ({base}..{base+per-1})")
print(f"HIGH SCORE (device, measured): {high} phases, {total} B, {seeded} blocks seeded")
print(f"control = 1536 B, so this is {100.0*total/1536:.0f}% of the control")
os.close(fd)
