# str_liczniki — dashboard WWW (FastAPI)

Dashboard odczytu: **PV** z tabeli `sofar_data`, mocy **L1–L3** z `licznik_pomiary` (liczniki 7 / 8 / 9), oraz **zużycia kWh** z `licznik_energia`.

## Wymagania

- Python 3.9+
- MySQL z tabelami zgodnymi ze schematem (patrz `app/str_data.py`)

## Instalacja

```bash
pip install -r requirements.txt
cp .env.example .env
```

Domyślnie aplikacja łączy się z **MySQL** (`10.10.0.21`, baza **`SOFAR_testy`** — patrz `app/settings.py`). W `.env` możesz nadpisać `DATABASE_URL` (inna baza, hasło). **Nie commituj `.env`**.

**Błąd `Unknown database`:** na serwerze MySQL musi istnieć baza o nazwie z URL (domyślnie `SOFAR_testy`), albo zmień ostatni segment w `DATABASE_URL` na **istniejącą** bazę z tabelami `sofar_data`, `licznik_pomiary`, `licznik_energia`:

```sql
CREATE DATABASE IF NOT EXISTS SOFAR_testy CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

**Logi:** przy starcie w konsoli i w pliku `logs/app.log` widać, czy test `SELECT 1` do bazy przeszedł; przy błędzie są podpowiedzi (np. brak bazy, hasło, sieć).

## Demo SQLite (bez MySQL)

```bash
export DATABASE_URL=sqlite:///./pv_demo.db
python3 -m app.init_demo_db
python3 run.py
```

## Uruchomienie

```bash
python run.py
```

Domyślnie: `http://0.0.0.0:8877` — strony: `/live`, `/chart`, `/meters`.

Porty **1–1023** (np. 88, 887) wymagają **root** albo `setcap` — zwykły użytkownik: ustaw `PORT=8877` w `.env`.

## Dostęp tylko z wybranych IP (Tailscale / LAN)

W pliku **`.env`** (obok projektu, nie jest w repozytorium) ustaw np.:

```env
ALLOWED_CLIENT_IPS=100.106.91.99
```

Można podać kilka adresów lub sieci **CIDR** po przecinku, np. `127.0.0.1,192.168.1.0/24`. **Pusta zmienna = brak blokady** (wszyscy mają dostęp).

Łączysz się przez **nginx** jako reverse proxy? Ustaw `TRUST_X_FORWARDED_FOR=true` i przekazuj `X-Forwarded-For` z prawdziwym IP klienta.

Po zmianie `.env` **zrestartuj** proces (`python run.py` / usługa).

**Timeout z przeglądarki (brak połączenia)** to zwykle **firewall / iptables**, nie `.env`.  
**HTTP 403** („Wejście”) = IP spoza `ALLOWED_CLIENT_IPS`.

Dla WireGuard używaj **`10.200.1.0/24`**, nie `10.200.1.0/10`.

## Ubuntu / WireGuard — port 88 działa, panel nie

Inny program (np. sport na porcie 88) może działać, bo jest na **sudo**; panel na **8877** — timeout z laptopa to zwykle **iptables**. Panel słucha na `0.0.0.0:8877`.

```bash
bash scripts/check-panel-port.sh
sudo bash scripts/open-firewall-port.sh 8877
```

Z laptopa (WG): `http://10.200.1.51:8877/live`  
Diagnostyka API (gdy TCP już działa): `GET /api/health` — widać `client_ip` i `client_allowed`.

Instalacja na serwerze:

```bash
bash install-ubuntu.sh
source .venv/bin/activate && python3 run.py
```

## Schemat bazy (MySQL)

- `sofar_data` — PV: `timestamp`, `moc_w`
- `licznik_pomiary` — `timestamp`, `licznik_id`, `moc_w`
- `licznik_energia` — `timestamp`, `licznik_id`, `energia_kwh` (skumulowane kWh)

ID liczników domyślnie: **7** Tomek, **8** Lonia, **9** Henia — zmiana przez `LICZNIK_*_ID` w `.env`.
