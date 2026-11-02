#!/bin/bash
# Backup a board's whole flash so it can be put back exactly, and PROVE the dump is trustworthy.
#
#     tools/backup_board.sh <port> <board-label> [size]
#     tools/backup_board.sh /dev/ttyUSB1 esp32s3 0x800000
#
# WHY A SCRIPT AND NOT A ONE-LINER: the Heltec V3 Meshtastic backup (backup/README.md) was done by hand, and the
# thing that made it usable was not `read_flash`, it was the two reads agreeing and the sha256 next to the file.
# A backup you have not verified is a file, not a backup.
#
# GUARDRAIL: two independent reads must hash IDENTICAL before the dump is kept (R19's read-side twin: never accept
# a flash artefact on the first try). A single read on a noisy USB link can come back with a corrupt window and
# every sha256 later "matches" the corruption, so restore fails at the worst possible moment.
# GUARDRAIL: refuse the port that is under test. /dev/ttyUSB0 is the Heltec console the probes talk to; a reset
# into the bootloader from this script would leave a running probe answering nothing and look like a firmware bug.
# GUARDRAIL: hold the board lock (probe/results/.board.lock) for the whole run, or a probe started during a 3-5
# minute read thinks the board is its own. And do not diagnose the lock from a second shell: a `flock -n` probe
# of mine answered "lock free" while this script held it, so an answer about the lock only means something from
# the process that would take it.
# GUARDRAIL: --after hard_reset, so the board runs its own firmware again when the dump is done. Leaving it in
# the bootloader made the NEXT person's serial session silent with no error at all.
set -euo pipefail
# `tools/backup_board.sh verify <port> <backup.bin>` re-reads the chip and proves the KEPT file is still the code
# on it (app partitions must match; nvs/spiffs drift is expected because the firmware writes them at runtime).
if [ "${1:-}" = verify ]; then
  VPORT=${2:?"usage: $0 verify <port> <backup.bin>"}
  VKEPT=${3:?"usage: $0 verify <port> <backup.bin>"}
  VROOT=$(cd "$(dirname "$0")/.." && pwd)
  VSIZE=$(stat -c %s "$VKEPT")
  exec 9>"$VROOT/probe/results/.board.lock"; flock -n 9 || { echo "REFUSED: board busy" >&2; exit 1; }
  echo "== re-reading $VSIZE B from $VPORT for comparison"
  esptool.py -p "$VPORT" -b 921600 --after no-reset read_flash 0 "$(printf '0x%X' "$VSIZE")" \
    "$VROOT/probe/results/verify-fresh.bin" >/dev/null 2>&1
  python3 "$VROOT/tools/backup_compare.py" "$VKEPT" "$VROOT/probe/results/verify-fresh.bin"
fi

PORT=${1:?"usage: $0 <port> <board-label> [size]"}
LABEL=${2:?"missing board label, e.g. esp32s3 / heltec-v3"}
SIZE=${3:-0x800000}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
LOCK=$ROOT/probe/results/.board.lock
STAGING=$ROOT/probe/results/backup-staging
mkdir -p "$ROOT/backup" "$STAGING"

case "$PORT" in
  /dev/ttyUSB0) echo "REFUSED: $PORT is the board under test (its console is how probes work)." >&2; exit 1;;
esac
[ -e "$PORT" ] || { echo "REFUSED: $PORT is not there." >&2; exit 1; }

exec 9>"$LOCK"; flock -n 9 || { echo "REFUSED: board lock held by another probe - not going to reset a mid-run board." >&2; exit 1; }
# GUARDRAIL: log to a file from INSIDE the script. The first run of this was launched by an agent harness and the
# harness aborted the TOOL CALL, not the process - so the dump kept reading with stdout gone, died on the first
# progress write (broken pipe), and left the board in the bootloader with a half-verified 8 MB file on disk. A backup
# has to own its own log, or its evidence dies with whoever started it. Run this under `tmux`, never inline.
LOG_DIR=$ROOT/probe/results
mkdir -p "$LOG_DIR"
LOG=$LOG_DIR/backup-$(date +%Y%m%d-%H%M%S).log
exec > >(tee -a "$LOG") 2>&1
echo "log: $LOG"

MAC=$(esptool.py --no-stub -p "$PORT" chip_id 2>/dev/null | awk '/MAC:/{print $2; exit}')
[ -n "${MAC:-}" ] || { echo "REFUSED: no MAC from $PORT - is it in bootloader mode / cabled right?" >&2; exit 1; }
MAC=$(echo "$MAC" | tr -d ':')
DATE=$(date +%Y%m%d-%H%M)
HUMAN=$(python3 -c 'import sys; a=int(sys.argv[1],0); print(f"{a//1024//1024}MB" if a % 1048576 == 0 else hex(a))' "$SIZE")
NAME="$LABEL-$MAC-$HUMAN-$DATE"
BIN="$ROOT/backup/$NAME.bin"
echo "== $PORT  chip MAC $MAC  size $SIZE"

# Two reads, and only a match is a backup.
for i in 1 2; do
  esptool.py -p "$PORT" -b 921600 --after no_reset read_flash 0 "$SIZE" "$STAGING/$NAME.read$i.bin" >/dev/null
done
H1=$(sha256sum "$STAGING/$NAME.read1.bin" | cut -d' ' -f1)
H2=$(sha256sum "$STAGING/$NAME.read2.bin" | cut -d' ' -f1)
[ "$H1" = "$H2" ] || { echo "REFUSED: two reads differ ($H1 vs $H2) - NOT a usable backup. Check leads/brownout." >&2; exit 1; }
cp "$STAGING/$NAME.read1.bin" "$BIN"
# GUARDRAIL: the third read is what ties the kept file to the chip, not to the staging copy: it is compared
# against the FILE, so a partial copy or a truncated 8 MB artefact cannot pass a self-hash of itself.
esptool.py -p "$PORT" -b 921600 --after no_reset read_flash 0 "$SIZE" "$STAGING/$NAME.read3.bin" >/dev/null
H3=$(sha256sum "$STAGING/$NAME.read3.bin" | cut -d' ' -f1)
[ "$H3" = "$H1" ] || { echo "REFUSED: third read disagrees with the kept dump." >&2; exit 1; }

esptool.py --no-stub -p "$PORT" chip_id 2>/dev/null > "$ROOT/backup/$NAME.identity.txt"
esptool.py -p "$PORT" --after no_reset read_flash 0 0x1000 "$ROOT/backup/$NAME.bootloader.bin" >/dev/null 2>&1 || true
( cd "$ROOT/backup" && sha256sum "$NAME.bin" > "$NAME.bin.sha256" )
rm -f "$STAGING/$NAME.read1.bin" "$STAGING/$NAME.read2.bin" "$STAGING/$NAME.read3.bin"

cat > "$ROOT/backup/$NAME.restore.md" <<EOF
# Restore $NAME

    esptool.py -p <port> -b 921600 write_flash 0 backup/$NAME.bin
    ( cd backup && sha256sum -c $NAME.bin.sha256 )   # before writing, and again on a re-read

Written by tools/backup_board.sh: three reads of the whole flash, all agreeing (sha256 \`$H1\`),
which is the only reason this file can be trusted later.
EOF
echo "== backup: $BIN"
echo "== sha256 : $H1 (three reads agreed)"
# GUARDRAIL: reset with the DTR/RTS toggle, not `esptool ... --after hard_reset run`. That form is wrong twice:
# esptool v5.3.1 renamed the choices to `hard-reset` (underscore exits 2) and `run` is not a reset command at all
# ("Usage: esptool.py run [OPTIONS]"). The failure lands AFTER a successful dump, so with `|| true` it hides - the
# board stays in the bootloader and the next serial session is silent for no visible reason. The toggle below is
# the same sequence the probes use on the Heltec and it demonstrably restarts the application.
python3 - "$PORT" <<'RESET'
import sys, time, serial
s = serial.Serial(sys.argv[1], 115200, timeout=0.2)
s.setDTR(False); s.setRTS(True); time.sleep(0.4); s.setRTS(False)
time.sleep(0.2); s.close()
print("== board reset into its own firmware")
RESET
