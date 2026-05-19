#!/bin/bash
# Diagnostyka: czy panel slucha i odpowiada lokalnie.
set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8877}"
if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a
  source .env 2>/dev/null || true
  set +a
  PORT="${PORT:-8877}"
fi

echo "=== str_liczniki — port $PORT ==="
echo ""
echo "1) Proces nasluchuje:"
ss -tlnp | grep ":$PORT " || echo "   BRAK — uruchom: source .venv/bin/activate && python3 run.py"
echo ""
echo "2) Lokalnie curl:"
curl -s -o /dev/null -w "   HTTP %{http_code}\n" --connect-timeout 3 "http://127.0.0.1:$PORT/live" || echo "   BRAK odpowiedzi"
echo ""
echo "3) Przez IP WG (jesli wg0):"
WG_IP=$(ip -4 -o addr show wg0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
if [ -n "$WG_IP" ]; then
  curl -s -o /dev/null -w "   http://$WG_IP:$PORT/live -> HTTP %{http_code}\n" --connect-timeout 3 "http://$WG_IP:$PORT/live" || echo "   BRAK"
else
  echo "   brak interfejsu wg0"
fi
echo ""
echo "4) iptables (port $PORT i 88):"
sudo iptables-save 2>/dev/null | grep -E "dport ($PORT|88)" || echo "   brak regul z grep"
echo ""
echo "5) ALLOWED_CLIENT_IPS:"
grep -E '^ALLOWED_CLIENT_IPS=' .env 2>/dev/null || echo "   (brak .env lub puste = wszyscy)"
echo ""
echo "Z laptopa WG: curl -v http://${WG_IP:-10.200.1.51}:$PORT/live"
echo "Timeout = firewall/routing. HTTP 403 = popraw ALLOWED_CLIENT_IPS w .env"
