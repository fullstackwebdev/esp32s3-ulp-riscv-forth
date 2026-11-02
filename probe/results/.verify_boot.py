import serial, time
s = serial.Serial("/dev/ttyUSB0", 115200, timeout=0.4)
s.write(b"\r\n"); time.sleep(1.2)
boot = s.read(900).decode("latin-1", "replace")
print("boot:", boot.replace("\r\n", "|")[:90])
s.write(b"1 2 + .\r\n"); time.sleep(0.8)
print("arith:", s.read(200).decode("latin-1", "replace").strip()[:24])
s.close()
