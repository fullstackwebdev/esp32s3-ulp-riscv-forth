import serial,time,re,sys
s=serial.Serial('/dev/ttyACM1',115200,timeout=0.2)
s.setDTR(False); s.setRTS(True); time.sleep(0.15); s.setRTS(False)
t0=time.time(); buf=b""
while time.time()-t0<5.0:
    c=s.read(512); buf+=c or b""
s.close()
txt=buf.decode('utf-8','replace')
m=re.search(r"p42 (\w+)\s+e=([0-9a-f]{8})\s+s=([0-9a-f]{8})\s+d=([0-9a-f]{8})\s+l=([0-9a-f]{8})\s+L=([0-9a-f]{8})", txt)
if not m: print("NO LINE:", txt[-200:]); sys.exit(1)
tag,e,sc,dc,lc,lcnt=m.groups(); e,sc,dc,lc,lcnt=[int(x,16) for x in (e,sc,dc,lc,lcnt)]
sl=(lc-sc)/(lcnt-dc) if lcnt>dc else 0
print("%-5s err=%d s=%d d=%d l=%d L=%d  slope=%.2f cyc/dispatch  intercept=%.0f" % (tag,e,sc,dc,lc,lcnt,sl,sc-sl*dc))
