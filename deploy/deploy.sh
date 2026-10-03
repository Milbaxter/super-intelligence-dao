#!/bin/bash
# Super Intelligence DAO deploy. Installed (root-owned, 0755) at /opt/super-intelligence-dao/deploy.sh by
# deploy/install.sh and run as user `sidao` via the GitHub Action's SSH forced command (SSH_ORIGINAL_COMMAND is ignored).
#
#   1. take a lock so two deploys never overlap
#   2. fetch origin/main
#   3. online, consistent SQLite backup of the live DB (keeps the newest 10 pre-deploy backups)
#   4. reset to origin/main, pip install -e, restart (sudo rule: sidao may run exactly
#      `/usr/bin/systemctl restart super-intelligence-dao`)
#   5. smoke check /api/v1/stats; on failure roll back the CODE to the previous commit and exit non-zero
#
# The DB is never restored automatically: schema migrations run on app start and are forward-only, so after a
# failed deploy the old code may be running against a migrated DB. If that is a problem, restore by hand
# (the exact command is printed on failure; see deploy/README.md).
set -euo pipefail

BASE=/opt/super-intelligence-dao
APP=$BASE/app
VENV=$BASE/venv
SERVICE=super-intelligence-dao
DB=/var/lib/super-intelligence-dao/agentdao.db
BACKUP_DIR=/var/lib/super-intelligence-dao/backups
KEEP_PRE_DEPLOY=10
LOCK=$BASE/.deploy.lock
SMOKE_URL=http://127.0.0.1:8790/api/v1/stats
SMOKE_TIMEOUT=30

log() { printf '[deploy %s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

# 1. Lock: a second deploy waits (up to 10 min) and then deploys whatever main is by then.
exec 9>"$LOCK"
flock -w 600 9 || die "another deploy is still holding $LOCK"

cd "$APP"
PREV=$(git rev-parse HEAD)
log "current commit ${PREV:0:7}"

# 2. Fetch first: if the network is down nothing has changed yet.
git fetch -q origin main
NEW=$(git rev-parse origin/main)
log "target commit ${NEW:0:7}"

# 3. Online backup via SQLite's backup API (safe while the app is writing; WAL mode). The venv python is used
#    because the sqlite3 CLI is not installed.
backup_db() {  # backup_db <src> <dst>
  "$VENV/bin/python" - "$1" "$2" <<'PY'
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
os.chmod(tmp, 0o640)
os.replace(tmp, dst_path)
PY
}

BACKUP=""
if [[ -f $DB ]]; then
  mkdir -p "$BACKUP_DIR"
  BACKUP=$BACKUP_DIR/pre-deploy-$(date -u +%Y%m%dT%H%M%SZ)-${PREV:0:7}.db
  backup_db "$DB" "$BACKUP"
  log "backed up DB -> $BACKUP ($(du -h "$BACKUP" | cut -f1))"
  # Prune: names sort chronologically; keep the newest $KEEP_PRE_DEPLOY.
  mapfile -t old < <(find "$BACKUP_DIR" -maxdepth 1 -name 'pre-deploy-*.db' -printf '%f\n' | sort -r | tail -n +$((KEEP_PRE_DEPLOY + 1)))
  for f in "${old[@]}"; do rm -f -- "${BACKUP_DIR:?}/$f"; done
  if ((${#old[@]})); then log "pruned ${#old[@]} old pre-deploy backup(s)"; fi
else
  log "no DB at $DB yet; skipping backup"
fi

install_and_restart() {  # install_and_restart <commit>; returns non-zero instead of exiting
  git reset -q --hard "$1" || return 1
  "$VENV/bin/pip" install -q -e . || return 1
  sudo -n /usr/bin/systemctl restart "$SERVICE" || return 1
}

smoke_check() {  # HTTP 200 + JSON object containing "phase", polled for up to $SMOKE_TIMEOUT s
  local deadline=$((SECONDS + SMOKE_TIMEOUT)) out code
  while ((SECONDS < deadline)); do
    if out=$(curl -sS --max-time 3 -w '\n%{http_code}' "$SMOKE_URL" 2>/dev/null); then
      code=${out##*$'\n'}
      if [[ $code == 200 ]] && printf '%s' "${out%$'\n'*}" |
          python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if isinstance(d, dict) and "phase" in d else 1)' 2>/dev/null; then
        return 0
      fi
    fi
    sleep 1
  done
  return 1
}

restore_hint() {
  [[ -n $BACKUP ]] || return 0
  log "the DB was NOT restored (migrations are forward-only). If the new code migrated it and the old code"
  log "cannot cope, restore the pre-deploy backup as root:"
  log "  systemctl stop $SERVICE && install -o sidao -g sidao -m 0640 $BACKUP $DB && rm -f $DB-wal $DB-shm && systemctl start $SERVICE"
}

# 4 + 5. Deploy, verify, roll back on failure.
if install_and_restart "$NEW" && smoke_check; then
  log "deployed ${NEW:0:7} (was ${PREV:0:7})"
  exit 0
fi

log "deploy of ${NEW:0:7} FAILED; rolling back code to ${PREV:0:7}"
journalctl -u "$SERVICE" -n 30 --no-pager 2>/dev/null || true
if install_and_restart "$PREV" && smoke_check; then
  log "rolled back to ${PREV:0:7}; service is healthy"
  restore_hint
  exit 1
fi
log "ROLLBACK FAILED: service is not healthy on ${PREV:0:7} either. Manual intervention needed."
restore_hint
exit 2
