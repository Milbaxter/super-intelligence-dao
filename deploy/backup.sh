#!/bin/bash
# Nightly online backup of the Super Intelligence DAO SQLite DB. Installed (root-owned, 0755) at
# /opt/super-intelligence-dao/backup.sh by deploy/install.sh; run as `sidao` by sidao-backup.service/.timer.
#
# Writes /var/lib/super-intelligence-dao/backups/daily-<UTC ts>.db.gz and keeps the newest 14.
# Off-box copy (off by default): set SIDAO_BACKUP_RSYNC_TARGET (e.g. backup@host:/srv/sidao/) in
# /etc/super-intelligence-dao.env; the file is rsynced over ssh with sidao's key (~sidao = /opt/super-intelligence-dao).
set -euo pipefail

DB=${AGENTDAO_DB:-/var/lib/super-intelligence-dao/agentdao.db}
BACKUP_DIR=${SIDAO_BACKUP_DIR:-/var/lib/super-intelligence-dao/backups}
KEEP_DAILY=14
PY=/opt/super-intelligence-dao/venv/bin/python
[[ -x $PY ]] || PY=python3

log() { printf '[backup] %s\n' "$*"; }

[[ -f $DB ]] || { log "no DB at $DB; nothing to back up"; exit 0; }
mkdir -p "$BACKUP_DIR"
umask 027

OUT=$BACKUP_DIR/daily-$(date -u +%Y%m%dT%H%M%SZ).db
# Consistent snapshot via SQLite's backup API (safe while the app is writing; the sqlite3 CLI is not installed).
"$PY" - "$DB" "$OUT" <<'PY'
import os, sqlite3, sys
from pathlib import Path
src_path, dst_path = sys.argv[1], sys.argv[2]
tmp = dst_path + ".tmp"
if os.path.exists(tmp):
    os.remove(tmp)
src = sqlite3.connect(Path(src_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
dst = sqlite3.connect(tmp)
src.backup(dst)                                   # one step => one consistent snapshot
dst.execute("PRAGMA journal_mode=DELETE")         # self-contained single file (no -wal/-shm needed)
check = dst.execute("PRAGMA quick_check").fetchone()[0]
dst.close(); src.close()
if check != "ok":
    os.remove(tmp)
    sys.exit(f"backup failed quick_check: {check}")
os.replace(tmp, dst_path)
PY
gzip -9 -f "$OUT"
OUT=$OUT.gz
log "wrote $OUT ($(du -h "$OUT" | cut -f1))"

# Prune: names sort chronologically; keep the newest $KEEP_DAILY.
mapfile -t old < <(find "$BACKUP_DIR" -maxdepth 1 -name 'daily-*.db.gz' -printf '%f\n' | sort -r | tail -n +$((KEEP_DAILY + 1)))
for f in "${old[@]}"; do rm -f -- "${BACKUP_DIR:?}/$f"; done
if ((${#old[@]})); then log "pruned ${#old[@]} old daily backup(s)"; fi

if [[ -n ${SIDAO_BACKUP_RSYNC_TARGET:-} ]]; then
  log "copying to $SIDAO_BACKUP_RSYNC_TARGET"
  rsync -t --partial -e "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20" \
    "$OUT" "$SIDAO_BACKUP_RSYNC_TARGET"
fi
