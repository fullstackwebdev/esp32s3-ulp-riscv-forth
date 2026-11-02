w("CREATE SBOX"); crows(SBOX)
w("CREATE RCON"); crows(RCON, 10)
w("CREATE BUF"); crows([0] * 16, 8)
for v in "ABCDE":
w("CREATE LEN 0 ,")
