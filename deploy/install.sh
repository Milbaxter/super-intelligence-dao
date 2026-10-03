#!/bin/bash
# Idempotent installer for the files in deploy/. Run as root from the app checkout:
#   sudo bash deploy/install.sh
# Safe to re-run (e.g. after deploy/ changes; the deploy itself never updates the installed scripts).
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run as root: sudo bash $0" >&2; exit 1; }

SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BASE=/opt/super-intelligence-dao
STATE=/var/lib/super-intelligence-dao
ENV_FILE=/etc/super-intelligence-dao.env
UNIT_DIR=/etc/systemd/system
SUMMARY=()
note() { SUMMARY+=("$*"); }

id sidao >/dev/null 2>&1 || { echo "user sidao does not exist" >&2; exit 1; }

# install_file <src> <dst> <mode> <owner:group> -> sets CHANGED=1 if the file was created/updated
install_file() {
  local src=$1 dst=$2 mode=$3 og=$4
  if [[ -f $dst ]] && cmp -s "$src" "$dst" && [[ $(stat -c '%a %U:%G' "$dst") == "${mode#0} $og" ]]; then
    note "unchanged  $dst"
  else
    install -o "${og%%:*}" -g "${og##*:}" -m "$mode" "$src" "$dst"
    note "installed  $dst ($mode $og)"
    CHANGED=1
  fi
}

# 1. Scripts: root-owned so the deploy key (user sidao) cannot rewrite what it runs.
CHANGED=0
install_file "$SRC/deploy.sh" "$BASE/deploy.sh" 0755 root:root
install_file "$SRC/backup.sh" "$BASE/backup.sh" 0755 root:root

# 2. Backups dir.
if [[ -d $STATE/backups ]]; then note "exists     $STATE/backups"; else note "created    $STATE/backups"; fi
install -d -o sidao -g sidao -m 0750 "$STATE/backups"

# 3. Backup units + timer.
CHANGED=0
install_file "$SRC/sidao-backup.service" "$UNIT_DIR/sidao-backup.service" 0644 root:root
install_file "$SRC/sidao-backup.timer" "$UNIT_DIR/sidao-backup.timer" 0644 root:root
if ((CHANGED)); then systemctl daemon-reload; note "ran        systemctl daemon-reload"; fi
if systemctl is-enabled --quiet sidao-backup.timer && systemctl is-active --quiet sidao-backup.timer; then
  if ((CHANGED)); then systemctl restart sidao-backup.timer; fi
  note "enabled    sidao-backup.timer (already)"
else
  systemctl enable --now sidao-backup.timer >/dev/null 2>&1
  note "enabled    sidao-backup.timer (now)"
fi

# 4. IP salt: generate a secret one if missing. The value is never printed.
SALT_ADDED=0
if [[ ! -f $ENV_FILE ]]; then
  note "WARNING    $ENV_FILE missing; AGENTDAO_IP_SALT not set"
elif grep -q '^AGENTDAO_IP_SALT=' "$ENV_FILE"; then
  note "unchanged  AGENTDAO_IP_SALT already set in $ENV_FILE"
else
  salt=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  [[ -z $(tail -c1 "$ENV_FILE") ]] || printf '\n' >>"$ENV_FILE"   # make sure we start on a fresh line
  printf 'AGENTDAO_IP_SALT=%s\n' "$salt" >>"$ENV_FILE"
  unset salt
  SALT_ADDED=1
  note "added      AGENTDAO_IP_SALT (random, 64 hex chars) to $ENV_FILE"
fi

# 5. Sanity checks (report only).
[[ -f /etc/sudoers.d/super-intelligence-dao ]] ||
  note "WARNING    /etc/sudoers.d/super-intelligence-dao missing: deploy.sh needs" \
       "'sidao ALL=(root) NOPASSWD: /usr/bin/systemctl restart super-intelligence-dao'"

echo "Super Intelligence DAO deploy/ install:"
printf '  %s\n' "${SUMMARY[@]}"
systemctl list-timers sidao-backup.timer --no-pager | sed 's/^/  /'
if ((SALT_ADDED)); then
  echo
  echo "  The new salt takes effect on the next restart: systemctl restart super-intelligence-dao"
  echo "  (Contributors registered before that keep hashes under the old salt; same-IP matching against them stops.)"
fi
