#!/bin/bash
# Instalacja zależności na Banana Pi / Raspberry Pi (ARM)
set -u
cd "$(dirname "$0")"

echo "=== str_liczniki — instalacja na Pi ==="

if ! command -v python3 >/dev/null 2>&1; then
  echo "Brak python3. Zainstaluj: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Tworzę .venv ..."
  python3 -m venv .venv
fi

# shellcheck source=/dev/null
source .venv/bin/activate

python -m pip install --upgrade pip wheel setuptools

# Stare pakiety FV (Pillow) — usuń, jeśli zostały z nieudanej instalacji
pip uninstall -y pdfplumber pillow pypdfium2 2>/dev/null || true

echo "Instaluję pakiety (requirements-pi.txt) ..."
if pip install --prefer-binary -r requirements-pi.txt; then
  echo "Pełna instalacja OK (z pypdf / FV)."
else
  echo ""
  echo "Uwaga: pełna lista się nie udała — instaluję tylko rdzeń (bez FV PDF) ..."
  pip install --prefer-binary -r requirements-pi-minimal.txt
fi

echo ""
echo "Sprawdzam importy:"
python -c "import uvicorn; import fastapi; print('  uvicorn + fastapi: OK')" || { echo "BŁĄD rdzenia"; exit 1; }
python -c "import pypdf; print('  pypdf (FV): OK')" 2>/dev/null || echo "  pypdf (FV): brak — zakładka FV nie wczyta PDF"

echo ""
echo "Gotowe. Start: source .venv/bin/activate && python run.py"
