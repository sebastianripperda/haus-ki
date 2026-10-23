#!/usr/bin/env bash
# Haus-KI auf Proxmox installieren: legt einen LXC-Container an und richtet die App darin ein.
# Auf dem Proxmox-Host als root ausführen, im entpackten Haus-KI-Ordner:
#   bash install/haus-ki-lxc.sh
# oder mit einem Paket:
#   bash haus-ki-lxc.sh --source /root/haus-ki-1.0.0.tar.gz
set -euo pipefail

BOLD=$'\e[1m'; DIM=$'\e[2m'; RED=$'\e[31m'; GRN=$'\e[32m'; YEL=$'\e[33m'; RST=$'\e[0m'
say()  { echo "${BOLD}›${RST} $*"; }
ok()   { echo "  ${GRN}✓${RST} $*"; }
warn() { echo "  ${YEL}!${RST} $*"; }
die()  { echo "${RED}✕ $*${RST}" >&2; exit 1; }
ask()  { local q="$1" def="${2:-}" a; if [ -n "${YES:-}" ]; then echo "$def"; return; fi
         read -rp "  $q${def:+ ${DIM}[$def]${RST}}: " a </dev/tty; echo "${a:-$def}"; }
yn()   { local a; a=$(ask "$1 (j/n)" "$2"); [[ "$a" =~ ^[jJyY] ]]; }

SOURCE=""; YES=""; DEBIAN_WANT=""
# Container sicher entfernen, auch wenn er nach einem Fehlstart gesperrt ist
remove_ct() {
  pct unlock "$1" >/dev/null 2>&1 || true
  pct stop "$1" --skiplock >/dev/null 2>&1 || true
  for _ in 1 2 3 4 5; do
    pct destroy "$1" --purge --force >/dev/null 2>&1 || true
    pct status "$1" >/dev/null 2>&1 || return 0
    sleep 2
  done
  return 1
}
while [ $# -gt 0 ]; do
  case "$1" in
    --source) SOURCE="$2"; shift 2 ;;
    --yes) YES=1; shift ;;
    --debian) DEBIAN_WANT="$2"; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) die "Unbekannte Option: $1" ;;
  esac
done

# ------------------------------------------------------------------ Voraussetzungen
[ "$(id -u)" -eq 0 ] || die "Bitte als root auf dem Proxmox-Host ausführen."
command -v pct >/dev/null && command -v pveversion >/dev/null || die "Das ist kein Proxmox-Host (pct fehlt)."
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
# Vorgaben aus der ausgefüllten Liste (ohne Geheimnisse)
CONF="$SCRIPT_DIR/haus-ki-install.conf"
# shellcheck disable=SC1090
[ -f "$CONF" ] && . "$CONF"
PEOPLE="$SCRIPT_DIR/haus-ki-personen.json"
if [ -z "$SOURCE" ]; then
  [ -f "$SCRIPT_DIR/../VERSION" ] || die "Kein Haus-KI-Ordner gefunden. Starte das Skript im entpackten Paket oder gib --source an."
  SRC_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
  VERSION=$(cat "$SRC_DIR/VERSION")
  tar -czf "$WORK/haus-ki.tar.gz" -C "$(dirname "$SRC_DIR")" --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' "$(basename "$SRC_DIR")"
else
  [ -f "$SOURCE" ] || die "Paket $SOURCE nicht gefunden."
  cp "$SOURCE" "$WORK/haus-ki.tar.gz"
  VERSION=$(tar -xzOf "$SOURCE" --wildcards '*/VERSION' | head -1)
fi
echo
echo "${BOLD}Haus-KI $VERSION – Installation auf $(hostname)${RST} ($(pveversion | cut -d/ -f2))"
echo "${DIM}Installationsskript Stand 1.2.7 mit Prüfung des Prozessortyps.${RST}"
echo "${DIM}Enter übernimmt jeweils den Vorschlag in Klammern.${RST}"
[ -f "$CONF" ] && echo "${DIM}Vorschläge aus $(basename "$CONF") übernommen.${RST}"
[ ! -f "$CONF" ] && [ -f "$CONF.example" ] && echo "${DIM}Tipp: Vorgaben lassen sich in install/haus-ki-install.conf hinterlegen (Vorlage: haus-ki-install.conf.example).${RST}"
[ -f "$PEOPLE" ] && echo "${DIM}Personen aus $(basename "$PEOPLE") werden vorab angelegt.${RST}"
echo

# ------------------------------------------------------------------ Fragen
say "Container"
CTID=$(ask "Container-ID" "${CTID:-$(pvesh get /cluster/nextid)}")
if pct status "$CTID" >/dev/null 2>&1; then
  if pct config "$CTID" 2>/dev/null | grep -q '^tags:.*haus-ki'; then
    warn "Container $CTID stammt von einem abgebrochenen Haus-KI-Lauf."
    if yn "Container $CTID löschen und neu anlegen" "j"; then
      remove_ct "$CTID" || die "Container $CTID ließ sich nicht löschen. Von Hand: pct unlock $CTID; pct destroy $CTID --purge --force"
      ok "Container $CTID gelöscht"
    else die "Bitte eine andere Container-ID wählen."; fi
  else die "Container $CTID gibt es schon und gehört nicht zu Haus-KI. Bitte eine andere ID wählen."; fi
fi
CT_HOST=$(ask "Name des Containers" "${CT_HOST:-haus-ki}")
STORAGES=$(pvesm status -content rootdir 2>/dev/null | awk 'NR>1 && $3=="active"{print $1}' | paste -sd' ')
STORAGE=$(ask "Speicher für den Container ($STORAGES)" "${STORAGE:-$(echo "$STORAGES" | awk '{print $1}')}")
# 4 Kerne und 4 GB, damit die Spracherkennung (Whisper „small“) flüssig läuft
DISK=$(ask "Festplatte in GB" "12")
RAM=$(ask "Arbeitsspeicher in MB" "4096")
CORES=$(ask "CPU-Kerne" "4")
BRIDGE=$(ask "Netzwerkbrücke" "${BRIDGE:-vmbr0}")
IPCFG=$(ask "IP-Adresse mit Präfix, z. B. 192.168.1.30/24, oder dhcp" "${IPCFG:-dhcp}")
if [ "$IPCFG" != "dhcp" ] && [ "${IPCFG#*/}" = "$IPCFG" ]; then IPCFG="$IPCFG/24"; warn "Kein Präfix angegeben, verwende $IPCFG"; fi
if [ "$IPCFG" != "dhcp" ]; then
  GW=$(ask "Gateway" "${GW:-$(ip route | awk '/default/{print $3; exit}')}")
  DNS=$(ask "DNS-Server" "${DNS:-$GW}")
else GW=""; DNS="${DNS:-}"; fi
DNSNAME=$(ask "Name im Heimnetz, z. B. ki.home (leer = IP-Adresse verwenden)" "${DNSNAME:-}")
echo
say "Ollama-Server (Container oder VM)"
{ pct list 2>/dev/null | awk 'NR>1{printf "    %s  %s (Container, %s)\n",$1,$NF,$2}'; qm list 2>/dev/null | awk 'NR>1{printf "    %s  %s (VM, %s)\n",$1,$2,$3}'; } | sort -n
DEF_ID=$(pct list 2>/dev/null | awk 'NR>1 && tolower($NF) ~ /ollama/{print $1; exit}')
[ -n "$DEF_ID" ] || DEF_ID=$(qm list 2>/dev/null | awk 'NR>1 && tolower($2) ~ /ollama/{print $1; exit}')
OLLAMA_VMID=$(ask "ID des Ollama-Containers" "${OLLAMA_VMID:-$DEF_ID}")
if pct status "$OLLAMA_VMID" >/dev/null 2>&1; then OLLAMA_KIND=lxc
elif qm status "$OLLAMA_VMID" >/dev/null 2>&1; then OLLAMA_KIND=qemu
else die "Einen Container oder eine VM mit ID $OLLAMA_VMID gibt es auf diesem Host nicht."; fi
NODE=$(hostname)
[ -n "${CONF_NODE:-}" ] && NODE="$CONF_NODE"
VM_IP=""; GUEST_EXEC=""
if [ "$OLLAMA_KIND" = lxc ]; then
  ok "$OLLAMA_VMID ist ein Container ($(pct status "$OLLAMA_VMID" | awk '{print $2}'))"
  OLLAMA_CORES=$(pct config "$OLLAMA_VMID" | awk '/^cores:/{print $2}')
  [ -n "$OLLAMA_CORES" ] && ok "$OLLAMA_CORES Kerne zugewiesen, Ollama bekommt passend viele Threads"
  if pct status "$OLLAMA_VMID" | grep -q running; then
    VM_IP=$(pct exec "$OLLAMA_VMID" -- hostname -I 2>/dev/null | awk '{print $1}') || true
    pct exec "$OLLAMA_VMID" -- systemctl is-active --quiet ollama 2>/dev/null && ok "Dienst ollama läuft im Container" \
      || warn "Im Container läuft kein Dienst „ollama“. Ist Ollama mit dem offiziellen Skript installiert?"
    GUEST_EXEC=1
  else
    warn "Der Container $OLLAMA_VMID läuft nicht. Bitte starten, dann das Skript erneut ausführen."
  fi
else
  ok "$OLLAMA_VMID ist eine VM"
  if qm agent "$OLLAMA_VMID" ping >/dev/null 2>&1; then
    VM_IP=$(qm guest cmd "$OLLAMA_VMID" network-get-interfaces 2>/dev/null | python3 -c '
import json,sys
for i in json.load(sys.stdin):
    if i.get("name")=="lo": continue
    for a in i.get("ip-addresses",[]):
        if a.get("ip-address-type")=="ipv4": print(a["ip-address"]); sys.exit()' || true)
    GUEST_EXEC=1
  fi
fi
[ -n "$VM_IP" ] && ok "IP-Adresse $VM_IP"
OLLAMA_URL=$(ask "Adresse von Ollama" "${OLLAMA_URL:-http://${VM_IP:-ollama}:11434}")
OLLAMA_OK=""
if V=$(curl -fsS -m 5 "$OLLAMA_URL/api/version" 2>/dev/null); then
  OLLAMA_OK=1; ok "Ollama $(echo "$V" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("version",""))') antwortet unter $OLLAMA_URL"
else warn "Ollama antwortet unter $OLLAMA_URL gerade nicht. Das lässt sich später in der Administration ändern."; fi
DO_PULL=""
if [ -n "$OLLAMA_OK" ]; then
  HAVE=$(curl -fsS -m 10 "$OLLAMA_URL/api/tags" 2>/dev/null | python3 -c 'import json,sys;print(" ".join(m["name"] for m in json.load(sys.stdin).get("models",[])))' 2>/dev/null) || HAVE=""
  MISSING=""
  WANT="qwen3:8b qwen3:4b llama3.2:3b"
  [ -n "${PAPERLESS_URL:-}" ] && WANT="$WANT bge-m3"   # für die Paperless-Suche nach Bedeutung
  # MoE-Modell zum Vergleich: viel Wissen, auf der CPU trotzdem schnell. Braucht etwa 19 GB RAM.
  OLLAMA_MEM=0
  [ "$OLLAMA_KIND" = lxc ] && OLLAMA_MEM=$(pct config "$OLLAMA_VMID" | awk '/^memory:/{print $2}')
  [ "$OLLAMA_KIND" = qemu ] && OLLAMA_MEM=$(qm config "$OLLAMA_VMID" | awk '/^memory:/{print $2}')
  case " $HAVE " in *" qwen3:30b-a3b "*) ;; *)
    if [ "${OLLAMA_MEM:-0}" -ge 30000 ] 2>/dev/null && yn "Zusätzlich qwen3:30b-a3b zum Vergleich laden (MoE, etwa 19 GB, passt zu ${OLLAMA_MEM} MB RAM)" "${PULL_MOE:-j}"; then
      WANT="$WANT qwen3:30b-a3b"
    fi ;;
  esac
  for m in $WANT; do case " $HAVE " in *" $m "*|*" $m:latest "*) ok "Modell $m vorhanden" ;; *) MISSING="$MISSING $m" ;; esac; done
  if [ -n "$MISSING" ]; then
    yn "Fehlende Modelle laden:$MISSING" "${PULL_MODELS:-j}" && DO_PULL=1
  fi
fi
INSTALL_AGENT=""; GUARD=""; OLLAMA_EXTRA=""; TUNE=""
if [ -n "$GUEST_EXEC" ]; then
  yn "Haus-KI-Agent automatisch im Ollama-Gast $OLLAMA_VMID installieren" "j" && INSTALL_AGENT=1
  if [ -n "$INSTALL_AGENT" ]; then
    if yn "Ollama schützen: Port 11434 nur noch für Haus-KI öffnen" "${GUARD_OLLAMA:-j}"; then
      GUARD=1
      OLLAMA_EXTRA=$(ask "Weitere Adressen, die Ollama direkt nutzen dürfen, mit Komma (leer = nur Haus-KI)" "${OLLAMA_EXTRA:-}")
    fi
    yn "Ollama für CPU einstellen (Flash Attention, halb so großer Kontextspeicher, Neustart von Ollama)" "${TUNE_OLLAMA:-j}" && TUNE=1
  fi
elif [ "$OLLAMA_KIND" = qemu ]; then
  warn "Der QEMU-Gastagent antwortet nicht. Den Haus-KI-Agenten installierst du später mit einem Befehl in der VM."
fi
echo

# ------------------------------------------------------------------ Paperless und Jellyfin
secret() {  # verdeckte Eingabe; ohne Terminal (z. B. --yes) einfach leer
  local q="$1" a=""
  if ( : </dev/tty ) 2>/dev/null; then read -rsp "  $q: " a </dev/tty || true; echo >&2; fi
  echo "$a"
}
say "Paperless-ngx"
PAPERLESS_URL=$(ask "Adresse (leer = später einrichten)" "${PAPERLESS_URL:-}")
PAPERLESS_TOKEN=""
if [ -n "$PAPERLESS_URL" ]; then
  PAPERLESS_URL=${PAPERLESS_URL%/}
  for try in 1 2 3; do
    if [ -n "${HAUSKI_PAPERLESS_TOKEN:-}" ]; then PAPERLESS_TOKEN=$HAUSKI_PAPERLESS_TOKEN; HAUSKI_PAPERLESS_TOKEN=""
    else PAPERLESS_TOKEN=$(secret "API-Token des Benutzers haus-ki (wird nicht angezeigt)"); fi
    [ -z "$PAPERLESS_TOKEN" ] && { warn "Kein Token, Paperless richtest du später in der Administration ein."; break; }
    HDR=$(mktemp)
    if BODY=$(curl -fsS -m 10 -D "$HDR" -H "Authorization: Token $PAPERLESS_TOKEN" -H "Accept: application/json; version=5" "$PAPERLESS_URL/api/documents/?page_size=1" 2>/dev/null); then
      N=$(echo "$BODY" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("count",0))')
      PV=$(awk -F': ' 'tolower($1)=="x-version"{print $2}' "$HDR" | tr -d '\r')
      ok "Paperless ${PV:+$PV }verbunden, $N Dokumente sichtbar"
      [ "$N" = "0" ] && warn "Der Benutzer haus-ki sieht keine Dokumente. Prüfe in Paperless die Rechte (alle Dokumente lesen)."
      rm -f "$HDR"; break
    fi
    rm -f "$HDR"
    warn "Paperless lehnt den Token ab oder ist nicht erreichbar ($PAPERLESS_URL)."
    [ "$try" = 3 ] && { warn "Paperless richtest du später in der Administration ein."; PAPERLESS_TOKEN=""; }
  done
fi
echo
say "Jellyfin"
JELLYFIN_URL=$(ask "Adresse (leer = später einrichten)" "${JELLYFIN_URL:-}")
JELLYFIN_KEY=""
if [ -n "$JELLYFIN_URL" ]; then
  JELLYFIN_URL=${JELLYFIN_URL%/}
  for try in 1 2 3; do
    if [ -n "${HAUSKI_JELLYFIN_KEY:-}" ]; then JELLYFIN_KEY=$HAUSKI_JELLYFIN_KEY; HAUSKI_JELLYFIN_KEY=""
    else JELLYFIN_KEY=$(secret "API-Schlüssel „Haus-KI“ (wird nicht angezeigt)"); fi
    [ -z "$JELLYFIN_KEY" ] && { warn "Kein Schlüssel, Jellyfin richtest du später in der Administration ein."; break; }
    if INFO=$(curl -fsS -m 10 -H "Authorization: MediaBrowser Client=\"Haus-KI\", Device=\"haus-ki\", DeviceId=\"haus-ki\", Version=\"1.1\", Token=\"$JELLYFIN_KEY\"" "$JELLYFIN_URL/System/Info" 2>/dev/null); then
      ok "Jellyfin $(echo "$INFO" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("Version",""),"auf",d.get("ServerName",""))') verbunden"
      break
    fi
    warn "Jellyfin lehnt den Schlüssel ab oder ist nicht erreichbar ($JELLYFIN_URL)."
    [ "$try" = 3 ] && { warn "Jellyfin richtest du später in der Administration ein."; JELLYFIN_KEY=""; }
  done
fi
echo

say "Websuche (Ollama Web Search)"
WEB_KEY=""
if yn "Websuche einrichten (nur wenn im Chat die Quelle „Internet“ eingeschaltet ist)" "${WEB_SEARCH:-j}"; then
  echo "  ${DIM}Schlüssel anlegen: ollama.com › Settings › Keys. Gesendet werden nur Suchbegriffe, keine Chats oder Dokumente.${RST}"
  for try in 1 2 3; do
    if [ -n "${HAUSKI_WEB_KEY:-}" ]; then WEB_KEY=$HAUSKI_WEB_KEY; HAUSKI_WEB_KEY=""
    else WEB_KEY=$(secret "API-Schlüssel für die Websuche (wird nicht angezeigt)"); fi
    [ -z "$WEB_KEY" ] && { warn "Kein Schlüssel, die Websuche richtest du später unter Administration › Quellen ein."; break; }
    if R=$(curl -fsS -m 15 -X POST "https://ollama.com/api/web_search" -H "Authorization: Bearer $WEB_KEY" \
           -H "Content-Type: application/json" -d '{"query": "Wetter Deutschland", "max_results": 1}' 2>/dev/null) \
       && echo "$R" | python3 -c 'import json,sys; sys.exit(0 if "results" in json.load(sys.stdin) else 1)' 2>/dev/null; then
      ok "Websuche funktioniert"
      break
    fi
    warn "Ollama.com lehnt den Schlüssel ab oder ist nicht erreichbar."
    [ "$try" = 3 ] && { warn "Die Websuche richtest du später unter Administration › Quellen ein."; WEB_KEY=""; }
  done
fi
echo

# ------------------------------------------------------------------ Vorlage
say "Debian-Vorlage"
pveam update >/dev/null 2>&1 || warn "Vorlagenliste konnte nicht aktualisiert werden."
AVAIL=$(pveam available --section system 2>/dev/null)
TPL_STORE=$(pvesm status -content vztmpl | awk 'NR>1 && $3=="active"{print $1; exit}')
HOST_ARCH=$(dpkg --print-architecture 2>/dev/null || true)
case "$HOST_ARCH" in amd64|arm64) ;; *) HOST_ARCH=amd64 ;; esac
ok "Prozessor des Hosts: $HOST_ARCH, es werden nur passende Vorlagen verwendet"
# Nur Vorlagen für den Prozessor des Hosts (Proxmox listet inzwischen auch arm64-Vorlagen)
template_for() {  # nur Vorlagen dieses Prozessortyps, andere ausdrücklich ausgeschlossen
  echo "$AVAIL" | awk -v v="^debian-$1-standard_.*_${HOST_ARCH}[.]tar" '$2 ~ v {print $2}' \
    | grep -F "_${HOST_ARCH}." | grep -vE "_(arm64|aarch64|i386|armhf)\." | sort -V | tail -1
}
fetch_template() {
  local have
  have=$(pveam list "$TPL_STORE" 2>/dev/null || true)
  if ! grep -qF "$1" <<<"$have"; then
    pveam download "$TPL_STORE" "$1" >/dev/null && ok "$1 heruntergeladen"
  else ok "$1 vorhanden"; fi
}
if [ -n "$DEBIAN_WANT" ]; then TEMPLATE=$(template_for "$DEBIAN_WANT")
else TEMPLATE=$(template_for 13); [ -n "$TEMPLATE" ] || TEMPLATE=$(template_for 12); fi
[ -n "$TEMPLATE" ] || die "Keine passende Debian-Vorlage gefunden. Ist der Host mit dem Internet verbunden?"
fetch_template "$TEMPLATE"

# ------------------------------------------------------------------ Container anlegen
NET="name=eth0,bridge=$BRIDGE,ip=$IPCFG"
[ -n "$GW" ] && NET="$NET,gw=$GW"
create_ct() {
  pct create "$CTID" "$TPL_STORE:vztmpl/$1" --hostname "$CT_HOST" --cores "$CORES" --memory "$RAM" --swap 512 \
    --rootfs "$STORAGE:$DISK" --net0 "$NET" --unprivileged 1 --features nesting=1,keyctl=1 --onboot 1 \
    --description "Haus-KI $VERSION – lokaler KI-Assistent" --tags haus-ki ${DNS:+--nameserver "$DNS"} >/dev/null
}
check_arch() {  # Prozessortyp von /sbin/init im Container prüfen (3e00 = amd64, b700 = arm64)
  local root want got
  case "$HOST_ARCH" in amd64) want="3e00" ;; arm64) want="b700" ;; *) return 0 ;; esac
  root=$(pct mount "$CTID" 2>/dev/null | sed -n "s/.*in '\(.*\)'.*/\1/p")
  [ -n "$root" ] || return 0
  got=$(od -An -tx1 -j18 -N2 "$root/usr/lib/systemd/systemd" 2>/dev/null | tr -d ' \n')
  pct unmount "$CTID" >/dev/null 2>&1 || true
  [ -z "$got" ] || [ "$got" = "$want" ] && return 0
  warn "Das System im Container ist für einen anderen Prozessor gebaut ($got statt $want)."
  return 1
}
start_ct() {
  check_arch || return 1
  pct start "$CTID" >/dev/null 2>&1 && return 0
  warn "Container $CTID startet nicht. Das meldet Proxmox:"
  pct start "$CTID" --debug 2>&1 | grep -viE '^\s*$' | tail -25 | sed 's/^/    /' >&2 || true
  return 1
}
case "$TEMPLATE" in *"_${HOST_ARCH}."*) ;; *) die "Vorlage $TEMPLATE passt nicht zur Architektur des Hosts ($HOST_ARCH)." ;; esac
say "Container $CTID anlegen ($TEMPLATE)"
create_ct "$TEMPLATE"
if ! start_ct; then
  if echo "$TEMPLATE" | grep -q debian-13 && [ -n "$(template_for 12)" ]; then
    if yn "Container löschen und mit Debian 12 neu anlegen" "j"; then
      remove_ct "$CTID" || die "Container $CTID ließ sich nicht löschen. Von Hand: pct unlock $CTID; pct destroy $CTID --purge --force"
      TEMPLATE=$(template_for 12)
      fetch_template "$TEMPLATE"
      create_ct "$TEMPLATE"
      start_ct || die "Auch mit Debian 12 startet der Container nicht. Bitte die Meldung oben schicken. Aufräumen: pct destroy $CTID --purge --force"
    else die "Abgebrochen. Aufräumen: pct destroy $CTID"; fi
  else
    die "Der Container startet nicht. Bitte die Meldung oben schicken. Aufräumen: pct destroy $CTID"
  fi
fi
ok "Container läuft"
for _ in $(seq 1 40); do
  CT_IP=$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}') || true
  [ -n "${CT_IP:-}" ] && pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1 && break
  sleep 2
done
[ -n "${CT_IP:-}" ] || die "Der Container bekommt keine IP-Adresse oder kein Internet. Prüfe Brücke und DHCP."
ok "IP-Adresse $CT_IP"
BASE_URL="https://${DNSNAME:-$CT_IP}"

# ------------------------------------------------------------------ Proxmox-Token
say "Proxmox-Zugang für Haus-KI"
pveum user add hauski@pve --comment "Haus-KI (nur Status und Steuerung des Ollama-Gasts)" 2>/dev/null || true
pveum role add HausKI --privs "VM.Audit,VM.PowerMgmt,Sys.Audit" 2>/dev/null || pveum role modify HausKI --privs "VM.Audit,VM.PowerMgmt,Sys.Audit"
pveum acl modify "/vms/$OLLAMA_VMID" --users hauski@pve --roles HausKI
pveum acl modify "/nodes/$NODE" --users hauski@pve --roles HausKI
pveum user token remove hauski@pve app 2>/dev/null || true
PVE_SECRET=$(pveum user token add hauski@pve app --privsep 0 --output-format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["value"])')
PVE_IP=${PVE_HOST:-$(ip -4 -br addr show "$BRIDGE" 2>/dev/null | awk '{sub(/\/.*/,"",$3); print $3}')}
[ -n "$PVE_IP" ] || PVE_IP=$(hostname -I | awk '{print $1}')
ok "Token hauski@pve!app angelegt (darf nur den Ollama-Gast $OLLAMA_VMID sehen, starten und neu starten)"

# ------------------------------------------------------------------ Agent im Ollama-Gast
AGENT_URL=""; AGENT_TOKEN=""
if [ -n "$INSTALL_AGENT" ]; then
  say "Haus-KI-Agent in $OLLAMA_VMID installieren"
  SRCROOT="$WORK/src"; mkdir -p "$SRCROOT"; tar -xzf "$WORK/haus-ki.tar.gz" -C "$SRCROOT"
  AGDIR=$(dirname "$(find "$SRCROOT" -name haus-ki-agent.py | head -1)")
  if [ "$OLLAMA_KIND" = lxc ]; then
    # Container: Dateien direkt hineinkopieren und ausführen, ohne Gastagent
    pct exec "$OLLAMA_VMID" -- mkdir -p /tmp/hk
    pct push "$OLLAMA_VMID" "$AGDIR/haus-ki-agent.py" /tmp/hk/haus-ki-agent.py
    pct push "$OLLAMA_VMID" "$AGDIR/install-agent.sh" /tmp/hk/install-agent.sh
    AG_OPTS="--allow $CT_IP${GUARD:+ --guard '$OLLAMA_EXTRA'}${TUNE:+ --tune}"
    TEXT=$(pct exec "$OLLAMA_VMID" -- bash -c "bash /tmp/hk/install-agent.sh $AG_OPTS; rc=\$?; rm -rf /tmp/hk; exit \$rc" 2>&1 || true)
  else
    A64=$(base64 -w0 "$AGDIR/haus-ki-agent.py"); I64=$(base64 -w0 "$AGDIR/install-agent.sh")
    OUT=$(qm guest exec "$OLLAMA_VMID" --timeout 180 -- bash -c "mkdir -p /tmp/hk && echo $A64 | base64 -d > /tmp/hk/haus-ki-agent.py && echo $I64 | base64 -d > /tmp/hk/install-agent.sh && bash /tmp/hk/install-agent.sh --allow $CT_IP${GUARD:+ --guard '$OLLAMA_EXTRA'}${TUNE:+ --tune}; rc=\$?; rm -rf /tmp/hk; exit \$rc" 2>&1 || true)
    TEXT=$(echo "$OUT" | python3 -c 'import json,sys
try: d=json.load(sys.stdin); print(d.get("out-data","")+d.get("err-data",""))
except Exception: print(sys.stdin.read())' 2>/dev/null || echo "$OUT")
  fi
  AGENT_URL=$(echo "$TEXT" | awk '/Adresse:/{print $2; exit}')
  AGENT_TOKEN=$(echo "$TEXT" | awk '/Token:/{print $2; exit}')
  GUARD_LINE=$(echo "$TEXT" | grep -m1 "Ollama-Schutz:" | sed 's/^ *//')
  echo "$TEXT" | grep -q "Ollama für CPU eingestellt" && ok "Ollama für CPU eingestellt"
  if [ -n "$AGENT_TOKEN" ]; then ok "Agent läuft unter $AGENT_URL"; [ -n "${GUARD_LINE:-}" ] && ok "$GUARD_LINE"; else warn "Agent-Installation hat nicht geklappt:"; echo "$TEXT" | tail -5 | sed 's/^/    /'; fi
fi

# ------------------------------------------------------------------ App einrichten
say "Haus-KI im Container einrichten (dauert ein paar Minuten)"
SECRET_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
SETUP_CODE=$(openssl rand -hex 3 | tr 'a-f' 'A-F')-$(openssl rand -hex 3 | tr 'a-f' 'A-F')
cat > "$WORK/haus-ki.env" <<EOF
HAUSKI_DATA=/var/lib/haus-ki
HAUSKI_SECRET_KEY=$SECRET_KEY
HAUSKI_BASE_URL=$BASE_URL
HAUSKI_SETUP_CODE=$SETUP_CODE
HAUSKI_SITE_NAMES="${DNSNAME:+$DNSNAME, }$CT_IP"
EOF
export WEB_KEY HAVE MISSING OLLAMA_CORES OLLAMA_KIND OLLAMA_URL PVE_IP PVE_SECRET NODE OLLAMA_VMID AGENT_URL AGENT_TOKEN PAPERLESS_URL PAPERLESS_TOKEN JELLYFIN_URL JELLYFIN_KEY \
  PAPERLESS_UPLOAD PAPERLESS_WRITE_TAGS PAPERLESS_DEADLINES PAPERLESS_DEADLINE_DAYS JELLYFIN_PLAYBACK PEOPLE
python3 - "$WORK/bootstrap.json" <<'PY'
import json, os, sys
e = os.environ.get
t = lambda k, d="true": (e(k) or d).strip().lower() in ("true", "ja", "j", "1", "yes")
data = {"ollama.url": e("OLLAMA_URL"), "proxmox.url": f"https://{e('PVE_IP')}:8006", "proxmox.token_id": "hauski@pve!app",
        "proxmox.token_secret": e("PVE_SECRET"), "proxmox.node": e("NODE"), "proxmox.vmid": int(e("OLLAMA_VMID") or 0), "proxmox.kind": e("OLLAMA_KIND") or "lxc",
        **({"req.num_thread": int(e("OLLAMA_CORES"))} if (e("OLLAMA_CORES") or "").isdigit() else {}),
        "agent.url": e("AGENT_URL") or "", "agent.token": e("AGENT_TOKEN") or "",
        "ollama.fast_model": "qwen3:4b" if "qwen3:4b" in ((e("HAVE") or "") + " " + (e("MISSING") or "")).split() else ""}
if e("PAPERLESS_URL") and e("PAPERLESS_TOKEN"):
    data.update({"paperless.enabled": True, "paperless.url": e("PAPERLESS_URL"), "paperless.token": e("PAPERLESS_TOKEN"),
                 "paperless.upload": t("PAPERLESS_UPLOAD"), "paperless.write_tags": t("PAPERLESS_WRITE_TAGS", "false"),
                 "paperless.deadlines": t("PAPERLESS_DEADLINES"), "paperless.deadline_days": int(e("PAPERLESS_DEADLINE_DAYS") or 14)})
if e("JELLYFIN_URL") and e("JELLYFIN_KEY"):
    data.update({"jellyfin.enabled": True, "jellyfin.url": e("JELLYFIN_URL"), "jellyfin.api_key": e("JELLYFIN_KEY"),
                 "jellyfin.playback": t("JELLYFIN_PLAYBACK")})
if e("WEB_KEY"):
    data.update({"web.enabled": True, "web.provider": "ollama", "web.ollama_key": e("WEB_KEY"), "web.max_results": 5})
if e("PEOPLE") and os.path.exists(e("PEOPLE")):
    data["users"] = json.load(open(e("PEOPLE")))
json.dump(data, open(sys.argv[1], "w"), indent=2)
PY
pct exec "$CTID" -- mkdir -p /etc/haus-ki
pct push "$CTID" "$WORK/haus-ki.env" /etc/haus-ki/haus-ki.env --perms 600
pct push "$CTID" "$WORK/bootstrap.json" /etc/haus-ki/bootstrap.json --perms 600
pct push "$CTID" "$WORK/haus-ki.tar.gz" /root/haus-ki.tar.gz
pct exec "$CTID" -- bash -c "mkdir -p /root/haus-ki-src && tar -xzf /root/haus-ki.tar.gz -C /root/haus-ki-src --strip-components=1 && bash /root/haus-ki-src/install/lxc-setup.sh" \
  || die "Die Einrichtung im Container ist fehlgeschlagen. Details: pct enter $CTID, dann journalctl -u haus-ki"
ok "Haus-KI läuft"
if [ -n "$DO_PULL" ]; then
  say "Modelle in Ollama laden (das dauert je nach Leitung einige Minuten)"
  for m in $MISSING; do
    if [ "$OLLAMA_KIND" = lxc ]; then
      # direkt im Ollama-Container, dort zeigt „ollama pull“ selbst den Fortschritt
      pct exec "$OLLAMA_VMID" -- ollama pull "$m" && ok "$m geladen" || warn "$m konnte nicht geladen werden. Das geht später unter Modelle."
    else
      # über den Haus-KI-Container, der Ollama auch mit Schutz erreichen darf
      pct exec "$CTID" -- curl -sN -X POST "$OLLAMA_URL/api/pull" -d "{\"model\": \"$m\"}" | python3 -c '
import json, sys
last = ""
for line in sys.stdin:
    try: d = json.loads(line)
    except ValueError: continue
    if "error" in d: print("\n    Fehler:", d["error"]); sys.exit(1)
    msg = "    %s: %d %%" % (sys.argv[1], d.get("completed", 0) * 100 // d["total"]) if d.get("total") else "    %s: %s" % (sys.argv[1], d.get("status", ""))
    if msg != last: print("\r" + msg.ljust(60), end="", flush=True); last = msg
print()' "$m" && ok "$m geladen" || warn "$m konnte nicht geladen werden. Das geht später unter Modelle."
    fi
  done
fi

# ------------------------------------------------------------------ Prüfen
say "Verbindungen prüfen"
if pct exec "$CTID" -- curl -fsS -m 5 "$OLLAMA_URL/api/version" >/dev/null 2>&1; then ok "Haus-KI erreicht Ollama"
else warn "Haus-KI erreicht Ollama unter $OLLAMA_URL nicht. Bitte in der Administration unter Anfrage-Standards prüfen."; fi
if [ -n "$GUARD" ] && [ -n "$AGENT_TOKEN" ]; then
  if curl -fsS -m 4 "$OLLAMA_URL/api/version" >/dev/null 2>&1; then warn "Ollama ist vom Proxmox-Host aus noch erreichbar. Der Schutz greift nicht, siehe Administration › Ollama-Server."
  else ok "Ollama ist von anderen Geräten aus gesperrt"; fi
fi

# ------------------------------------------------------------------ Sicherung in Proxmox
BK_STORES=$(pvesm status -content backup 2>/dev/null | awk 'NR>1 && $3=="active"{print $1}' | paste -sd' ')
if [ -n "$BK_STORES" ]; then
  say "Nächtliche Sicherung des Containers"
  BK_DEF=$(echo "$BK_STORES" | tr ' ' '\n' | grep -v '^local$' | head -1); BK_DEF=${BK_DEF:-$(echo "$BK_STORES" | awk '{print $1}')}
  if yn "Container $CTID jede Nacht um 03:30 sichern" "j"; then
    BK=$(ask "Speicher für die Sicherung ($BK_STORES)" "${BACKUP_STORAGE:-$BK_DEF}")
    if pvesh create /cluster/backup --vmid "$CTID" --storage "$BK" --schedule "03:30" --mode snapshot --compress zstd \
         --prune-backups "keep-daily=7,keep-weekly=4" --enabled 1 --comment "Haus-KI" >/dev/null 2>&1; then
      ok "Sicherung auf $BK eingerichtet (7 tägliche, 4 wöchentliche)"
      [ "$BK" = local ] && warn "„local“ liegt auf derselben Platte wie der Container. Besser ein NAS oder einen Proxmox Backup Server wählen."
    else warn "Die Sicherung ließ sich nicht anlegen. In Proxmox unter Rechenzentrum › Backup von Hand einrichten."; fi
  fi
fi

# ------------------------------------------------------------------ Fertig
cat <<EOF

${GRN}${BOLD}Fertig.${RST}

  Adresse:           ${BOLD}$BASE_URL${RST}
  Einrichtungscode:  ${BOLD}$SETUP_CODE${RST}   (nur für die Ersteinrichtung im Browser)
  Container:         $CTID ($CT_HOST), IP $CT_IP

Nächste Schritte
  1. Zertifikat der Haus-KI auf euren Geräten vertrauen: http://$CT_IP/ca.crt herunterladen und installieren.
     Ohne diesen Schritt zeigt der Browser eine Warnung, die Verbindung ist trotzdem verschlüsselt.
EOF
if [ -n "$DNSNAME" ]; then
  echo "  2. Im Router einen DNS-Eintrag anlegen: $DNSNAME → $CT_IP"
else
  echo "  2. Optional: einen Namen wie ki.home im Router auf $CT_IP zeigen lassen und HAUSKI_BASE_URL in /etc/haus-ki/haus-ki.env anpassen."
fi
FIRST_ADMIN=""
[ -f "$PEOPLE" ] && FIRST_ADMIN=$(python3 -c 'import json,sys; print(next((p["name"] for p in json.load(open(sys.argv[1])) if p.get("role") == "admin"), ""))' "$PEOPLE" 2>/dev/null || true)
if [ -n "$FIRST_ADMIN" ]; then
  echo "  3. $BASE_URL öffnen, Einrichtungscode eingeben und als Namen „$FIRST_ADMIN“ wählen (die vorab angelegte Person wird übernommen)."
else
  echo "  3. $BASE_URL öffnen, Einrichtungscode eingeben und den ersten Administrator mit Notfall-Passwort anlegen."
fi
if [ -z "$AGENT_TOKEN" ]; then
  echo "  4. Im Ollama-Container den Agenten installieren (Proxmox › Container $OLLAMA_VMID › Konsole):"
  echo "     curl -fsSLk $BASE_URL/agent/install.sh | bash -s -- --allow $CT_IP"
  echo "     Adresse und Token danach in der Administration unter Ollama-Server eintragen."
fi
echo
echo "${DIM}Updates: neues Paket in der Administration unter Updates und Sicherung hochladen.${RST}"
