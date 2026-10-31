#!/bin/bash
# Holds the board lock for the whole P06 run (bash tool calls are separate shells,
# so fd 9 cannot be inherited; a tmux-held flock is the persistent equivalent).
cd /home/user/research/esp32-rv32 || exit 1
exec 9>probe/results/.board.lock
if flock -n 9; then
  echo ACQUIRED > probe/results/P06-wake/.lockstate
  sleep 900
else
  echo BUSY > probe/results/P06-wake/.lockstate
fi
