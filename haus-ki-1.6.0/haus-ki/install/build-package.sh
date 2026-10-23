#!/usr/bin/env bash
# Baut das Installationspaket haus-ki-<version>.tar.gz im übergeordneten Ordner.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VER=$(cat "$ROOT/VERSION")
OUT="${1:-$(dirname "$ROOT")}/haus-ki-$VER.tar.gz"
# Eigene Vorgaben und Personen gehören nie in ein Paket, das man weitergibt
tar -czf "$OUT" -C "$(dirname "$ROOT")" --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' --exclude='.git' \
  --exclude='install/haus-ki-install.conf' --exclude='install/haus-ki-personen.json' --exclude='*.db' --exclude='.env' \
  "$(basename "$ROOT")"
if tar -tzf "$OUT" | grep -qE 'haus-ki-install\.conf$|haus-ki-personen\.json$'; then
  echo "Abbruch: persönliche Vorgaben im Paket gefunden." >&2; rm -f "$OUT"; exit 1
fi
( cd "$(dirname "$OUT")" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )
echo "$OUT"
