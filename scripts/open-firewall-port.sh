#!/bin/bash
# Jawne ACCEPT na porcie panelu (gdy dziala :88 a :8765 timeout z WG — czesto iptables).
# Uzycie: sudo bash scripts/open-firewall-port.sh [PORT]
set -euo pipefail
PORT="${1:-8765}"

echo "=== Otwieram TCP $PORT (eth0 + wg0) w iptables ==="

if ! command -v iptables >/dev/null 2>&1; then
  echo "Brak iptables"
  exit 1
fi

# Na poczatek lancucha INPUT — przed ewentualnym DROP
sudo iptables -I INPUT 1 -p tcp --dport "$PORT" -j ACCEPT
if ip link show wg0 &>/dev/null; then
  sudo iptables -I INPUT 1 -i wg0 -p tcp --dport "$PORT" -j ACCEPT
fi

echo "Reguly dodane. Sprawdz:"
sudo iptables -L INPUT -n -v --line-numbers | head -15
echo ""
echo "Zapis na stale (opcjonalnie):"
echo "  sudo apt install -y iptables-persistent"
echo "  sudo netfilter-persistent save"
