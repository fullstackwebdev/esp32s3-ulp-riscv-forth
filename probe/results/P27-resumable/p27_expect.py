#!/usr/bin/env python3
"""Host-side predictions for P27. Computed from the SCHEDULING RULE ONLY (round-robin,
quantum = one PAUSE, done tasks skipped) and from arithmetic on the Forth source text.
Nothing here is read from the VM's output."""
NT = 3
NAMES = "ABC"
ITERS = {"A": 5, "B": 3, "C": 4}

def next_ready(cur, ready):
    order = list(NAMES)
    i = order.index(cur)
    for k in range(1, NT + 1):
        n = order[(i + k) % NT]
        if ready[n]:
            return n
    return None

ready = {n: True for n in NAMES}
counts = {n: 0 for n in NAMES}
left = dict(ITERS)
cur = "A"
log = ["->A"]
steps = 0
while True:
    steps += 1
    if steps > 100:
        raise SystemExit("prediction model did not terminate")
    if left[cur] > 0:
        left[cur] -= 1
        counts[cur] += 1
        to = next_ready(cur, ready)
        log.append(cur + ">" + to)
        cur = to
    else:
        ready[cur] = False
        to = next_ready(cur, ready)
        if to is None:
            # nothing to switch TO, so this is a retire, not a switch: the rule needs a target
            break
        log.append(cur + ">" + to)
        cur = to

print("A-ORDER: " + " ".join(log))
print("A-COUNTS: " + " ".join("%s=%d" % (n, counts[n]) for n in NAMES))
# (b): 7 3 * 5 +  DUP *      = ((7*3)+5)^2
b = ((7 * 3) + 5) ** 2
print("B-RESULT: %d" % b)
# (c): 0 5 0 DO I + LOOP      = sum 0..4
c = sum(range(0, 5))
print("C-RESULT: %d" % c)
# (d) re-runs the same two words with a fault instead of a pause: same numbers.
print("D-RESULT: %d %d" % (b, c))
