# deploy/

Production ops files for the UpCloud box (service `super-intelligence-dao`, user `sidao`, app checkout
`/opt/super-intelligence-dao/app`, DB `/var/lib/super-intelligence-dao/agentdao.db`).

| File | What it does |
|---|---|
| `deploy.sh` | Run by the GitHub Action (SSH forced command, as `sidao`). Locks (flock), backs up the DB online to `backups/pre-deploy-<ts>-<sha>.db` (keeps 10), resets to `origin/main`, `pip install -e`, restarts, smoke-checks `/api/v1/stats`. On failure it rolls the **code** back to the previous commit and exits non-zero. It never restores the DB (migrations are forward-only); it prints the restore command instead. |
| `backup.sh` | Nightly online backup to `backups/daily-<ts>.db.gz` (keeps 14). If `SIDAO_BACKUP_RSYNC_TARGET` (e.g. `user@host:/srv/sidao/`) is set in `/etc/super-intelligence-dao.env`, also rsyncs the file over ssh with sidao's key. Off by default. |
| `sidao-backup.service` / `.timer` | Runs `backup.sh` as `sidao` daily around 03:17 UTC. |
| `install.sh` | Idempotent root installer: copies `deploy.sh`/`backup.sh` to `/opt/super-intelligence-dao/` (root:root 0755), installs and enables the backup timer, creates the backups dir, and adds a random `AGENTDAO_IP_SALT` to the env file if it is missing. |

Backups use SQLite's online backup API through the venv's Python (no `sqlite3` CLI needed), so they are
consistent while the app is running. Each one is a self-contained single file.

## Install / update

The deploy never updates the installed scripts. After pulling changes to `deploy/`, run this from the app checkout:

```sh
cd /opt/super-intelligence-dao/app && sudo bash deploy/install.sh
```

If the salt was just added, restart the service: `sudo systemctl restart super-intelligence-dao`.

Run a backup now: `sudo systemctl start sidao-backup.service && journalctl -u sidao-backup -n 20`.

## Restore a backup

```sh
B=/var/lib/super-intelligence-dao/backups/<file>          # pre-deploy-*.db or daily-*.db.gz
DB=/var/lib/super-intelligence-dao/agentdao.db
sudo systemctl stop super-intelligence-dao
sudo cp -a "$DB" "$DB.before-restore"                      # optional safety copy
case "$B" in *.gz) sudo sh -c "gunzip -c '$B' > '$DB'";; *) sudo cp "$B" "$DB";; esac
sudo chown sidao:sidao "$DB" && sudo chmod 0640 "$DB"
sudo rm -f "$DB-wal" "$DB-shm"
sudo systemctl start super-intelligence-dao
```

If the backup came from older code than what is now checked out, the app migrates it forward on start. If it
came from newer code, check out the matching commit (the `<sha>` in `pre-deploy-*` names is the code that was
running when the backup was taken).
