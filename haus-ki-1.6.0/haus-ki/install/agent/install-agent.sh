#!/usr/bin/env bash
# Haus-KI-Agent im Ollama-Container installieren.
#   curl -fsSLk __HAUSKI_URL__/agent/install.sh | sudo bash
# Optionen: --allow <IP von haus-ki>  --port 8765  --uninstall
#           --guard "<weitere IPs>"  Ollama-Port nur für Haus-KI (und diese Adressen) öffnen
#           --tune                   Ollama für CPU einstellen (Flash Attention, kompakter Kontextspeicher)
set -euo pipefail

HAUSKI_URL="__HAUSKI_URL__"
PORT=8765
ALLOW=""
GUARD=""; GUARD_EXTRA=""; TUNE=""
DIR=/opt/haus-ki-agent
CONF=/etc/haus-ki-agent

while [ $# -gt 0 ]; do
  case "$1" in
    --allow) ALLOW="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --guard) GUARD=1; GUARD_EXTRA="${2:-}"; shift 2 ;;
    --tune) TUNE=1; shift ;;
    --uninstall)
      systemctl disable --now haus-ki-agent 2>/dev/null || true
      rm -rf "$DIR" "$CONF" /etc/systemd/system/haus-ki-agent.service
      systemctl daemon-reload
      command -v nft >/dev/null && nft delete table inet hauski_guard 2>/dev/null && echo "Schutz für Ollama entfernt, Port 11434 ist wieder für alle offen."
      echo "Agent entfernt. Die Ollama-Einstellungen in /etc/systemd/system/ollama.service.d/haus-ki.conf bleiben erhalten."
      exit 0 ;;
    *) echo "Unbekannte Option: $1"; exit 1 ;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "Bitte als root ausführen (sudo)."; exit 1; }
if ! command -v python3 >/dev/null; then
  echo "python3 fehlt, wird installiert …"
  apt-get update -qq && apt-get install -y -qq python3 >/dev/null || { echo "python3 ließ sich nicht installieren."; exit 1; }
fi
command -v openssl >/dev/null || { apt-get update -qq && apt-get install -y -qq openssl; }
systemctl list-unit-files ollama.service >/dev/null 2>&1 || { echo "Kein Dienst ollama.service gefunden. Ist Ollama installiert?"; exit 1; }

if [ -z "$ALLOW" ] && [ "${HAUSKI_URL#__}" = "$HAUSKI_URL" ]; then
  HOST=$(echo "$HAUSKI_URL" | sed -E 's#^https?://([^/:]+).*#\1#')
  ALLOW=$(getent ahostsv4 "$HOST" | awk 'NR==1{print $1}' || true)
fi

echo "Installiere Haus-KI-Agent …"
mkdir -p "$DIR" "$CONF"
chmod 700 "$CONF"
if [ -f "$(dirname "$0")/haus-ki-agent.py" ]; then
  cp "$(dirname "$0")/haus-ki-agent.py" "$DIR/"
else
  curl -fsSLk "$HAUSKI_URL/agent/haus-ki-agent.py" -o "$DIR/haus-ki-agent.py"
fi
chmod 755 "$DIR/haus-ki-agent.py"
# Eine Kopie dieses Skripts behalten, damit „--uninstall“ später ohne Paket funktioniert
[ -f "$0" ] && [ "$(readlink -f "$0")" != "$(readlink -f "$DIR/install-agent.sh")" ] && install -m 755 "$0" "$DIR/install-agent.sh"

if [ ! -f "$CONF/agent.key" ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=$(hostname)" \
    -keyout "$CONF/agent.key" -out "$CONF/agent.crt" >/dev/null 2>&1
  chmod 600 "$CONF/agent.key"
fi

TOKEN=$(openssl rand -hex 32)
HASH=$(printf '%s' "$TOKEN" | sha256sum | cut -d' ' -f1)
if [ -n "$GUARD" ] && ! command -v nft >/dev/null; then
  echo "nftables wird installiert …"
  apt-get update -qq && apt-get install -y -qq nftables >/dev/null || { echo "nftables ließ sich nicht installieren, Schutz übersprungen."; GUARD=""; }
fi
python3 - "$CONF/config.json" "$HASH" "$PORT" "$ALLOW" "$CONF" "$GUARD" "$GUARD_EXTRA" <<'PY'
import json, re, sys
path, h, port, allow, conf, guard, extra = sys.argv[1:]
ips = [allow] if allow else []
ips += [x for x in re.split(r"[ ,;]+", extra) if re.match(r"^(\d{1,3}\.){3}\d{1,3}(/\d{1,2})?$", x) and x not in ips]
json.dump({"token_sha256": h, "port": int(port), "bind": "0.0.0.0", "allowed_ips": [allow] if allow else [],
           "guard": bool(guard and allow), "ollama_allow": ips,
           "cert": conf + "/agent.crt", "key": conf + "/agent.key"}, open(path, "w"), indent=2)
PY
chmod 600 "$CONF/config.json"

cat > /etc/systemd/system/haus-ki-agent.service <<EOF
[Unit]
Description=Haus-KI-Agent (Ollama-Einstellungen)
After=network-online.target ollama.service

[Service]
ExecStart=/usr/bin/python3 $DIR/haus-ki-agent.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=false
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
# Ollama für CPU einstellen: Flash Attention und halb so großer Kontextspeicher
if [ -n "$TUNE" ]; then
  OV=/etc/systemd/system/ollama.service.d/haus-ki.conf
  mkdir -p "$(dirname "$OV")"
  [ -f "$OV" ] || printf '# Verwaltet von Haus-KI\n[Service]\n' > "$OV"
  for kv in OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0; do
    grep -q "Environment=\"${kv%%=*}=" "$OV" || echo "Environment=\"$kv\"" >> "$OV"
  done
  systemctl daemon-reload
  systemctl restart ollama && echo "Ollama für CPU eingestellt (Flash Attention, Kontextspeicher q8_0)."
fi
systemctl daemon-reload
systemctl enable --now haus-ki-agent >/dev/null
systemctl restart haus-ki-agent
GUARD_STATE=$(python3 "$DIR/haus-ki-agent.py" --apply-guard 2>&1 || true)

# Ollama muss für Haus-KI im Netz erreichbar sein.
if ss -ltn 2>/dev/null | grep -q '127.0.0.1:11434'; then
  echo
  echo "Hinweis: Ollama lauscht nur auf 127.0.0.1. Haus-KI kann es so nicht erreichen."
  echo "Setze in der Administration unter Ollama-Server OLLAMA_HOST=0.0.0.0:11434 und starte neu,"
  echo "oder jetzt sofort mit:  echo 'Environment=\"OLLAMA_HOST=0.0.0.0:11434\"' …"
fi

IP=$(hostname -I | awk '{print $1}')
FP=$(openssl x509 -in "$CONF/agent.crt" -noout -fingerprint -sha256 | cut -d= -f2 | tr -d ':' | tr 'A-F' 'a-f')
cat <<EOF

Haus-KI-Agent läuft.

  Adresse:      https://$IP:$PORT
  Token:        $TOKEN
  Fingerabdruck: $FP
  Erlaubt für:  ${ALLOW:-alle Adressen (mit --allow <IP> einschränken)}
  Ollama-Schutz: $( [ "$GUARD_STATE" = aktiv ] && echo "aktiv, Port 11434 nur für ${ALLOW}${GUARD_EXTRA:+, $GUARD_EXTRA}" || echo "${GUARD_STATE:-aus}")

Trag Adresse und Token in Haus-KI unter Administration › Ollama-Server ein.
Das Token wird hier nur einmal angezeigt. Ein neues erzeugst du, indem du dieses Skript erneut ausführst.
EOF
