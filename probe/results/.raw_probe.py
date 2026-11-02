import serial, time

s = serial.Serial("/dev/ttyUSB0", 115200, timeout=0.4)
s.setDTR(False); s.setRTS(True); time.sleep(0.3); s.setRTS(False)
time.sleep(2.0); s.reset_input_buffer(); s.read(65536)


def raw(c, t=0.6):
    s.write(c.encode() + b"\r\n"); time.sleep(t)
    return s.read(900).decode("latin-1", "replace").strip().replace("\r\n", " | ")


src = "/home/user/research/esp32-rv32/examples/apps/lora/lora1.fs"
for line in open(src).read().splitlines():
    line = line.strip()
    if not line or line.startswith("\\"):
        continue
    r = raw(line, 0.35)
    if "?" in r or "ERR" in r:
        print("  LOAD PROBLEM:", line[:50], "->", r[:70])

print("HERE after driver:", raw("HERE .", 0.6)[:40])
word = ": RAMREADBIT WB IF [ 30 >B 0 >B 0 >B <C ] ELSE 99 THEN ;"
print("def  ->", raw(word, 0.9)[:100])
print("call ->", raw("RAMREADBIT .", 0.9)[:60])
print("prims present: WB ->", raw("WORD? WB", 0.5)[:40])
s.close()
