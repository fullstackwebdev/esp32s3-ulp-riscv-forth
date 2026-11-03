#!/bin/sh
# GUARDRAIL: a killed test can leave a `meshtastic --listen` child holding the port; every later flash or --set then
# fails with "Resource temporarily unavailable" and looks like a board fault. Free the ports before any board work.
for dev in /dev/ttyUSB0 /dev/ttyUSB1; do
  for p in /proc/[0-9]*; do
    pid=${p#/proc/}
    for f in "$p"/fd/*; do
      [ "$(readlink "$f" 2>/dev/null)" = "$dev" ] && { echo "freeing $dev from pid $pid ($(tr '\0' ' ' < "$p/cmdline" 2>/dev/null | cut -c1-60))"; kill -9 "$pid" 2>/dev/null; }
    done
  done
done
sleep 1
