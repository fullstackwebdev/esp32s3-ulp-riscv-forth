/* msg_codes.h — the ONE list of every message the ULP console can print (R6).
 *
 * The ULP writes ONE byte per message into repl_out[]; main/repl_main.c turns that byte back into the
 * text below before it reaches the operator. The ULP build compiles only the enumerators (the text
 * lives on the HP core, which has 32 MB of flash to hold it); the HP build compiles only the strings.
 * One list, two expansions: a code can never mean two different things, and a message that exists on
 * one side and not the other fails to compile instead of printing nothing.
 *
 * GUARDRAIL: codes start at 0x81 because every byte the ULP otherwise puts in the ring is ASCII — the
 * echo is `c >= 32 && c < 127` (drain_cmd), the number printer emits '-', digits and ' '
 * (uforth.c P_DOT), and the error path emits the offending word from PAD plus '?' and '\n' (err()).
 * Nothing the engine can emit is >= 0x80, so 0x80 and up is a free escape space; 0x80 itself is
 * deliberately NOT a code, so the "is this a code?" test is one comparison and an off-by-one cannot
 * turn into a silent pass-through of a non-ASCII byte.
 *
 * GUARDRAIL: APPEND ONLY. One byte with the wrong meaning prints a plausible sentence about the wrong
 * thing, which is worse to debug than a crash — the codes are a wire format between two cores that
 * are always flashed together, so changing one is a change to both. 0x89.. are reserved for the
 * -DP42_BENCH image (not in the shipping build).
 */
#ifndef MSG_CODES_H
#define MSG_CODES_H

#define MSG_BASE 0x81

/* X(name, code, text) — text is exactly what the ULP used to emit, byte for byte. */
#define MSG_LIST(X)                                            \
  X(MSG_ERASE,         0x81, "\b \b")                          \
  X(MSG_LINE_TOO_LONG, 0x82, "\nline too long\n")              \
  X(MSG_UNDERFLOW,     0x83, "stack?\n")                       \
  X(MSG_OK,            0x84, " ok\n")                          \
  X(MSG_BANNER,        0x85, "\nulp forth\n ok\n")             \
  X(MSG_TASK_STACK,    0x86, "\ntasks need an empty stack\n")  \
  X(MSG_ERR_DICT,      0x87, "ERR_DICT ")                      \
  X(MSG_ERR_TASKS,     0x88, "ERR_TASKS ")                   \
  X(MSG_ERR_STACK,     0x89, "ERR_STACK ")

/* The names, for the ULP (which uses them and never sees the text) and for host code that wants to
 * emit a code in a test. Enum constants cost no storage: the strings above are only macro arguments. */
#define MSG_ENUM(name, code, text) name = code,
enum { MSG_LIST(MSG_ENUM) };
#undef MSG_ENUM

#endif
