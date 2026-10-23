#!/usr/bin/env bash
# Haus-KI installieren, aktualisieren oder zurücksetzen. Läuft als root im Container.
#   haus-ki-update.sh --install-from <ordner>   (Erstinstallation)
#   haus-ki-update.sh                          (Auftrag aus /var/lib/haus-ki/updates/request, von der Oberfläche)
#   haus-ki-update.sh --rollback
set -euo pipefail
BASE=/opt/haus-ki
UPD=/var/lib/haus-ki/updates
STATUS=$UPD/status.json
mkdir -p "$UPD"

status() { printf '{"state": "%s", "message": "%s", "ts": %s}\n' "$1" "$2" "$(date +%s)" > "$STATUS"; chown hauski:hauski "$STATUS" 2>/dev/null || true; echo "$2"; }

healthy() { for _ in $(seq 1 45); do curl -fs -o /dev/null http://127.0.0.1:8080/health && return 0; sleep 2; done; return 1; }

install_units() {
  cp "$BASE/current/install/systemd/"*.service "$BASE/current/install/systemd/"*.path /etc/systemd/system/
  install -m 755 "$BASE/current/install/haus-ki-update.sh" /usr/local/sbin/haus-ki-update
  systemctl daemon-reload
  systemctl enable haus-ki.service haus-ki-update.path >/dev/null 2>&1
  systemctl start haus-ki-update.path
}

deploy() {  # $1 = entpackter Quellordner
  local src="$1" ver dest
  ver=$(cat "$src/VERSION")
  dest="$BASE/releases/$ver"
  [ -d "$dest" ] && dest="$dest-$(date +%Y%m%d%H%M%S)"
  mkdir -p "$dest"
  cp -a "$src/." "$dest/"
  python3 -m venv "$dest/venv"
  "$dest/venv/bin/pip" install -q --disable-pip-version-check -r "$dest/app/requirements.txt"
  chown -R root:root "$dest"
  [ -L "$BASE/current" ] && ln -sfn "$(readlink "$BASE/current")" "$BASE/previous"
  ln -sfn "$dest" "$BASE/current"
  install_units
  systemctl restart haus-ki
  if healthy; then
    status ok "Haus-KI $ver läuft."
    ls -1dt "$BASE"/releases/* | tail -n +4 | xargs -r rm -rf   # die letzten drei Versionen behalten
  else
    if [ -L "$BASE/previous" ]; then
      ln -sfn "$(readlink "$BASE/previous")" "$BASE/current"
      systemctl restart haus-ki
      status error "Version $ver startete nicht. Haus-KI läuft wieder mit der vorherigen Version."
    else
      status error "Version $ver startete nicht. Details: journalctl -u haus-ki"
    fi
    return 1
  fi
}

backup_db() {
  local db=/var/lib/haus-ki/haus-ki.db
  [ -f "$db" ] || return 0
  mkdir -p /var/lib/haus-ki/backups
  local dst
  dst="/var/lib/haus-ki/backups/vor-update-$(date +%Y%m%d-%H%M).db"
  python3 -c 'import sqlite3, sys; s = sqlite3.connect(sys.argv[1]); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()' "$db" "$dst"
  gzip -f "$dst"
  chown -R hauski:hauski /var/lib/haus-ki/backups
}

case "${1:-}" in
  --install-from) deploy "$2" ;;
  --rollback)
    [ -L "$BASE/previous" ] || { status error "Es gibt keine vorherige Version."; exit 1; }
    cur=$(readlink "$BASE/current"); ln -sfn "$(readlink "$BASE/previous")" "$BASE/current"; ln -sfn "$cur" "$BASE/previous"
    systemctl restart haus-ki; healthy && status ok "Zur vorherigen Version zurückgekehrt." ;;
  *)
    [ -f "$UPD/request" ] || exit 0
    action=$(python3 -c 'import json;print(json.load(open("/var/lib/haus-ki/updates/request"))["action"])' 2>/dev/null || echo "")
    rm -f "$UPD/request"
    if [ "$action" = "rollback" ]; then exec "$0" --rollback; fi
    [ -f "$UPD/incoming.tar.gz" ] || { status error "Kein Paket gefunden."; exit 1; }
    status running "Update wird installiert …"
    trap 'status error "Update abgebrochen (Zeile $LINENO). Haus-KI läuft weiter mit der bisherigen Version. Details: journalctl -u haus-ki-update"' ERR
    tmp=$(mktemp -d)
    tar -xzf "$UPD/incoming.tar.gz" -C "$tmp" || { status error "Das Paket ist beschädigt."; exit 1; }
    src=$(dirname "$(find "$tmp" -maxdepth 2 -name VERSION | head -1)")
    [ -f "$src/app/hauski/main.py" ] || { status error "Das ist kein Haus-KI-Paket."; rm -rf "$tmp"; exit 1; }
    backup_db
    deploy "$src" || true
    rm -rf "$tmp" "$UPD/incoming.tar.gz" ;;
esac
