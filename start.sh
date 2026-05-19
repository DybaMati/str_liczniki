#!/bin/bash
# Uruchomienie panelu (Banana Pi / Raspberry Pi) — skrót .desktop
set -u
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Brak .venv — uruchamiam install-pi.sh ..."
  bash install-pi.sh || exit 1
fi

# shellcheck source=/dev/null
source .venv/bin/activate

if ! python -c "import uvicorn" 2>/dev/null; then
  echo "Brak uvicorn — uruchamiam install-pi.sh ..."
  bash install-pi.sh || exit 1
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "Start — http://${IP:-localhost}:887"
exec python run.py
