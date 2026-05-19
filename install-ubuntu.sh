#!/bin/bash
# Instalacja na Ubuntu/Debian (x86_64) — to samo co install-pi.sh, requirements.txt
set -euo pipefail
cd "$(dirname "$0")"

echo "=== str_liczniki — instalacja (Ubuntu) ==="

if ! command -v python3 >/dev/null 2>&1; then
  echo "Zainstaluj: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  exit 1
fi

if ! python3 -c "import venv" 2>/dev/null; then
  echo "Zainstaluj: sudo apt install -y python3-venv"
  exit 1
fi

[ -d .venv ] || python3 -m venv .venv
# shellcheck source=/dev/null
source .venv/bin/activate
PY="${VIRTUAL_ENV}/bin/python3"

$PY -m pip install --upgrade pip wheel setuptools
$PY -m pip install -r requirements.txt

$PY -c "import uvicorn, fastapi, pypdf; print('OK: uvicorn, fastapi, pypdf')"

echo ""
echo "Nastepnie:"
echo "  cp .env.example .env && nano .env"
echo "  source .venv/bin/activate && python3 run.py"
echo "  (jesli z WG timeout na porcie) sudo bash scripts/open-firewall-port.sh"
