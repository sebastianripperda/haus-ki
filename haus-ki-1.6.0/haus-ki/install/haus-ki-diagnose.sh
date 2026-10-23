#!/usr/bin/env bash
# Findet heraus, warum der Haus-KI-Container nicht startet.
# Legt kurzlebige Test-Container an (freie ID), ändert jeweils nur eine Einstellung,
# startet sie und löscht sie sofort wieder. Bestehende Container werden nicht angefasst.
#   bash install/haus-ki-diagnose.sh
set -uo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Bitte als root ausführen."; exit 1; }

# Vorgaben aus install/haus-ki-install.conf, falls vorhanden
CONF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/haus-ki-install.conf"
# shellcheck disable=SC1090
[ -f "$CONF" ] && . "$CONF"
STORAGE=${STORAGE:-local-lvm}
BRIDGE=${BRIDGE:-vmbr0}
IP=${IP:-${IPCFG:-dhcp}}
GW=${GW:-}
DNS=${DNS:-${GW:-}}
ID=$(pvesh get /cluster/nextid)
TPL_STORE=$(pvesm status -content vztmpl | awk 'NR>1 && $3=="active"{print $1; exit}')
ARCH=$(dpkg --print-architecture 2>/dev/null || true)
case "$ARCH" in amd64|arm64) ;; *) ARCH=amd64 ;; esac
echo "Diagnose Stand 1.2.7, Prozessor des Hosts: $ARCH"

tpl() {  # vorhandene oder herunterladbare Vorlage
  local name
  name=$(pveam list "$TPL_STORE" 2>/dev/null | awk -v v="$1_.*_${ARCH}[.]tar" '$1 ~ v {sub(/.*vztmpl\//,"",$1); print $1}' | sort -V | tail -1)
  if [ -z "$name" ]; then
    name=$(pveam available --section system 2>/dev/null | awk -v v="^$1_.*_${ARCH}[.]tar" '$2 ~ v {print $2}' | sort -V | tail -1)
    [ -n "$name" ] && pveam download "$TPL_STORE" "$name" >/dev/null 2>&1
  fi
  echo "$name"
}
D13=$(tpl debian-13-standard)
D12=$(tpl debian-12-standard)
U24=$(tpl ubuntu-24.04-standard)
echo "Test-ID $ID, Speicher $STORAGE"
echo "Vorlagen: ${D13:-keine Debian 13} / ${D12:-keine Debian 12} / ${U24:-keine Ubuntu 24.04}"

cleanup() {  # Test-Container sicher entfernen, auch nach missglücktem Start
  pct unlock "$ID" >/dev/null 2>&1
  pct stop "$ID" --skiplock >/dev/null 2>&1
  pct destroy "$ID" --purge --force >/dev/null 2>&1
  for _ in 1 2 3 4 5; do pct status "$ID" >/dev/null 2>&1 || return 0; sleep 2; pct destroy "$ID" --purge --force >/dev/null 2>&1; done
  echo; echo "Test-Container $ID lässt sich nicht löschen. Bitte von Hand entfernen: pct destroy $ID --purge --force"; exit 1
}
errors() {  # nur echte Fehlerzeilen aus der LXC-Ausgabe
  grep -E '(^|[[:space:]])(ERROR|WARN)[[:space:]]' "$1" | grep -viE 'sequence number|Failed to spawn container|__lxc_start' \
    | sed -E 's/^.*(ERROR|WARN)[[:space:]]+//' | head -3 | tr '\n' ' '
}
echo

RESULTS=(); N=0
rm -f /root/haus-ki-diagnose-test*.log
try() {  # $1 Beschreibung, $2 Vorlage, $3 Netz, $4 weitere Optionen
  local label="$1" t="$2" net="$3" extra="$4" out first
  [ -z "$t" ] && { RESULTS+=("–     $label (Vorlage fehlt)"); return; }
  local up="--unprivileged 1"; case "$extra" in *--unprivileged*) up="" ;; esac
  printf '  %-58s ' "$label"
  # shellcheck disable=SC2086
  if ! out=$(pct create "$ID" "$TPL_STORE:vztmpl/$t" --hostname hk-test --cores 1 --memory 512 --rootfs "$STORAGE:2" \
       --net0 "$net" $up $extra 2>&1); then
    first=$(echo "$out" | grep -v '^\s*$' | tail -1)
    echo "ANLEGEN FEHLGESCHLAGEN"; RESULTS+=("FEHL  $label: $first"); return
  fi
  if pct start "$ID" >/dev/null 2>&1; then
    echo "startet"; RESULTS+=("OK    $label")
  else
    local log
    N=$((N + 1)); log="/root/haus-ki-diagnose-test$N.log"
    pct unlock "$ID" >/dev/null 2>&1; pct stop "$ID" --skiplock >/dev/null 2>&1
    pct start "$ID" --debug > "$log" 2>&1
    first=$(errors "$log")
    echo "STARTET NICHT"; RESULTS+=("FEHL  $label: ${first:-siehe $log}")
  fi
  cleanup
}

GWOPT=""; [ "$IP" != dhcp ] && [ -n "$GW" ] && GWOPT=",gw=$GW"
N_FW="name=eth0,bridge=$BRIDGE,ip=$IP$GWOPT,firewall=1"
N_NOFW="name=eth0,bridge=$BRIDGE,ip=$IP$GWOPT"
N_DHCP="name=eth0,bridge=$BRIDGE,ip=dhcp"

echo "Starte Tests (je etwa 20 Sekunden):"
try "1 wie das Installationsskript: Debian 13, Firewall, DNS" "$D13" "$N_FW" "--features nesting=1,keyctl=1 ${DNS:+--nameserver $DNS}"
try "2 wie 1, aber ohne Firewall-Option"                          "$D13" "$N_NOFW" "--features nesting=1,keyctl=1 ${DNS:+--nameserver $DNS}"
try "3 wie 1, aber Debian 12"                                     "$D12" "$N_FW" "--features nesting=1,keyctl=1 ${DNS:+--nameserver $DNS}"
try "4 Debian 12, ohne Firewall-Option"                           "$D12" "$N_NOFW" "--features nesting=1,keyctl=1 ${DNS:+--nameserver $DNS}"
try "5 Debian 13 wie Container 105: DHCP, ohne Firewall, kein DNS" "$D13" "$N_DHCP" "--features nesting=1,keyctl=1"
try "6 Debian 13 ganz schlicht: DHCP, ohne Zusatzfunktionen"       "$D13" "$N_DHCP" ""
try "7 Ubuntu 24.04 wie Container 105"                            "$U24" "$N_DHCP" "--features nesting=1,keyctl=1"
try "8 Debian 13 privilegiert (nur zum Test)"                     "$D13" "$N_DHCP" "--unprivileged 0"

echo
echo "================ Ergebnis (bitte komplett schicken) ================"
pveversion | head -1
printf '%s\n' "${RESULTS[@]}"
ls -1 /root/haus-ki-diagnose-test*.log 2>/dev/null | sed 's/^/Protokoll: /'
echo "===================================================================="
