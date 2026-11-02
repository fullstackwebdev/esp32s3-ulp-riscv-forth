import pathlib, textwrap
SBOX = [
0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16]
RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36]
L = []
def w(s=""):
    if s.lstrip().startswith("\\"):
        for part in textwrap.wrap(s.lstrip("\\ ").strip(), width=59) or [""]:
            L.append(("\\ " + part).rstrip())
        return
    assert len(s) <= 63, f"CODE line too long ({len(s)}): {s}"
    L.append(s)
def crows(vals, per=8):
    for i in range(0, len(vals), per):
        w("  " + " ".join(f"{v} C," for v in vals[i:i+per]))
for h in [
 "lora_aes.fs - AES-128 (key schedule, block, CTR) in Forth on the ULP.",
 "",
 "WHY: a Meshtastic frame is encrypted in place with AES-CTR. This file is the cipher only: no radio pins, no SPI",
 "primitives, so it can sit in a phase window by itself. Cost measured in docs/31.",
 "",
 "GUARDRAIL: a control structure must be COMPLETE on one typed line. Measured: BEGIN..WHILE on one line and REPEAT",
 "on the next answers ERR_STACK and the word never exists; IF..THEN across lines behaves the same. Loops therefore",
 "drive globals (A B C D LEN) and the body is a named helper, which also keeps lines under 63 B (the ring drops",
 "longer lines silently).",
 "",
 "GUARDRAIL: 256 B of S-box plus 176 B of round keys is the budget item; the code is the cheap part. The KEY",
 "SCHEDULE is deliberately NOT here: measured, schedule + block together exceed the 1 328 B prompt dictionary."
 "",
 "Layout follows FIPS-197: SBOX, then the ten round constants.",
]: w("\\" + (" " + h if h else ""))
w("CREATE SBOX"); crows(SBOX)
w("CREATE RCON"); crows(RCON, 10)
w("\\ Round keys (44 words of 4 B), state, key/payload buffer, scratch, nonce.")
w("CREATE W"); crows([0] * 176, 8)
w("CREATE ST"); crows([0] * 16, 8)
w("CREATE BUF"); crows([0] * 16, 8)
w("CREATE TZ"); crows([0] * 16, 8)
w("CREATE NONC"); crows([0] * 16, 8)
for v in "ABCDE":
    w(f"CREATE {v} 0 ,")
w("CREATE LEN 0 ,")
w("")
for x in [
 "\\ ---- byte helpers ----------------------------------------------------",
 ": CB ( n -- b ) ST + C@ ;",
 ": TS! ( b o -- ) TZ + C! ;",
 ": SBY A @ ST + DUP C@ SBOX + C@ SWAP C! ;",
 ": CPY A @ TZ + C@ A @ ST + C! ;",
 ": CPYS 0 A ! BEGIN A @ 16 < WHILE CPY A @ 1+ A ! REPEAT ;",
 "",
 "\\ ---- SubBytes --------------------------------------------------------",
 ": SFULL 0 A ! BEGIN A @ 16 < WHILE SBY A @ 1+ A ! REPEAT ;",
 "",
 "\\ ---- ShiftRows: TZ[i] = ST[src], src = 4*((col+row)&3)+row --------------",
 ": ROW A @ 3 AND ;",
 ": COL A @ 2 RSHIFT ;",
 ": SRS ( -- src ) COL ROW + 3 AND 2 LSHIFT ROW + ;",
 ": STR A @ SRS ST + C@ A @ TS! ;",
 ": SR 0 A ! BEGIN A @ 16 < WHILE STR A @ 1+ A ! REPEAT CPYS ;",
 "",
 "\\ ---- MixColumns ------------------------------------------------------",
 ": XTZ DUP 128 AND IF 2 * 255 AND 27 XOR ELSE 2 * 255 AND THEN ;",
 ": MCO B @ 4 * ;",
 ": A0 MCO CB ;",
 ": A1 MCO 1+ CB ;",
 ": A2 MCO 2 + CB ;",
 ": A3 MCO 3 + CB ;",
 ": B0 A0 XTZ A1 XTZ A1 XOR XOR A2 XOR A3 XOR ;",
 ": B1 A0 A1 XTZ XOR A2 XTZ A2 XOR XOR A3 XOR ;",
 ": B2 A0 A1 XOR A2 XTZ XOR A3 XTZ A3 XOR XOR ;",
 ": B3 A0 XTZ A0 XOR A1 XOR A2 XOR A3 XTZ XOR ;",
 ": MCS B0 MCO TS! B1 MCO 1+ TS! ;",
 ": MCS2Z B2 MCO 2 + TS! B3 MCO 3 + TS! ;",
 ": MCB MCS MCS2Z B @ 1+ B ! ;",
 ": MC 0 B ! BEGIN B @ 4 < WHILE MCB REPEAT CPYS ;",
 "",
 "\\ ---- AddRoundKey -----------------------------------------------------",
 ": ARKB A @ ST + DUP C@ A @ C @ 16 * + W + C@ XOR SWAP C! ;",
 ": ARKQQQQQ 0 A ! BEGIN A @ 16 < WHILE ARKB A @ 1+ A ! REPEAT ;",
 "",
 "\\ ---- key schedule ----------------------------------------------------",
 ": KB ( k -- b ) W + C@ ;",
 "",
 "\\ ---- the block -------------------------------------------------------",
 ": RNDB SFULL SR MC ARKQQQQQ C @ 1+ C ! ;",
 ": RNDS 1 C ! BEGIN C @ 10 < WHILE RNDB REPEAT ;",
 ": FIN 10 C ! SFULL SR ARKQQQQQ ;",
 ": AESB 0 C ! ARKQQQQQ RNDS FIN ;",
 "",
 "\\ ---- CTR -------------------------------------------------------------",
 "\\ NONC holds the 16-byte counter block; its last byte is the counter, so one",
 "\\ block covers BUF (16 B) - enough for Data{portnum,payload}. Larger frames",
 "\\ need the block loop, and that is stated rather than half-implemented.",
 ": CPYC A @ NONC + C@ A @ ST + C! ;",
 ": CPYN 0 A ! BEGIN A @ 16 < WHILE CPYC A @ 1+ A ! REPEAT ;",
 ": CXB BUF A @ + DUP C@ A @ ST + C@ XOR SWAP C! ;",
 ": CXOR 0 A ! BEGIN A @ LEN @ < WHILE CXB A @ 1+ A ! REPEAT ;",
 ": INCB 15 NONC + DUP C@ 1+ SWAP C! ;",
 ": CTR LEN ! CPYN AESB CXOR INCB ;"]:
    w(x)
p = pathlib.Path("examples/apps/lora/lora_aes.fs"); p.write_text("\n".join(L) + "\n")
n = sum(len([t for t in l.split() if t == "C,"]) for l in L)
print("lines:", len(L), "| longest:", max(len(x) for x in L), "| C, parity:", "even" if n % 2 == 0 else "ODD")
