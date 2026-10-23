#!/usr/bin/env bash
# Läuft im Container: installiert Haus-KI aus /root/haus-ki-src. Wird vom Proxmox-Skript aufgerufen.
set -euo pipefail
SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VERSION=$(cat "$SRC/VERSION")
export DEBIAN_FRONTEND=noninteractive
. /etc/haus-ki/haus-ki.env

echo "  Pakete installieren …"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip caddy curl sqlite3 ca-certificates tzdata libgomp1 >/dev/null
id hauski >/dev/null 2>&1 || useradd --system --home /var/lib/haus-ki --shell /usr/sbin/nologin hauski
mkdir -p /opt/haus-ki/releases /var/lib/haus-ki/public /var/lib/haus-ki/updates
chown -R hauski:hauski /var/lib/haus-ki
chown root:hauski /etc/haus-ki /etc/haus-ki/*; chmod 750 /etc/haus-ki; chmod 640 /etc/haus-ki/*

echo "  Haus-KI $VERSION installieren …"
bash "$SRC/install/haus-ki-update.sh" --install-from "$SRC"

echo "  Webserver (Caddy) einrichten …"
SITES="${HAUSKI_SITE_NAMES:-$(hostname -I | awk '{print $1}')}"
HTTP_SITES=$(echo "$SITES" | sed 's/[^, ]\+/http:\/\/&/g')
cat > /etc/caddy/Caddyfile <<CADDY
# Verwaltet von Haus-KI
$SITES {
	tls internal
	encode gzip
	reverse_proxy 127.0.0.1:8080 {
		flush_interval -1
	}
}

$HTTP_SITES {
	handle /ca.crt {
		root * /var/lib/haus-ki/public
		rewrite * /root.crt
		file_server
	}
	handle /agent/* {
		reverse_proxy 127.0.0.1:8080
	}
	handle {
		redir https://{host}{uri} permanent
	}
}
CADDY
systemctl enable caddy >/dev/null 2>&1
systemctl restart caddy
for _ in $(seq 1 30); do
  ROOT=/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt
  [ -f "$ROOT" ] && { cp "$ROOT" /var/lib/haus-ki/public/root.crt; chmod 644 /var/lib/haus-ki/public/root.crt; break; }
  curl -sk -o /dev/null "https://127.0.0.1/" || true
  sleep 1
done
for _ in $(seq 1 30); do curl -fs -o /dev/null http://127.0.0.1:8080/health && break; sleep 2; done
curl -fsS http://127.0.0.1:8080/health >/dev/null || { journalctl -u haus-ki -n 30 --no-pager; exit 1; }
rm -rf /root/haus-ki.tar.gz
