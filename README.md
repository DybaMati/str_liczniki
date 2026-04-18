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

Domyślnie aplikacja łączy się z **MySQL** (`10.10.0.21`, baza `scada` — patrz `app/settings.py`). W `.env` możesz nadpisać `DATABASE_URL` (inna baza, hasło). **Nie commituj `.env`**.

**Błąd `Unknown database 'scada'`:** na serwerze MySQL musi istnieć baza o nazwie z URL (domyślnie `scada`), albo zmień ostatni segment w `DATABASE_URL` na **istniejącą** bazę, gdzie są tabele `sofar_data`, `licznik_pomiary`, `licznik_energia`:

```sql
CREATE DATABASE IF NOT EXISTS scada CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
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

Domyślnie: `http://0.0.0.0:8765` — strony: `/live`, `/chart`, `/meters`.

## Schemat bazy (MySQL)

- `sofar_data` — PV: `timestamp`, `moc_w`
- `licznik_pomiary` — `timestamp`, `licznik_id`, `moc_w`
- `licznik_energia` — `timestamp`, `licznik_id`, `energia_kwh` (skumulowane kWh)

ID liczników domyślnie: **7** Tomek, **8** Lonia, **9** Henia — zmiana przez `LICZNIK_*_ID` w `.env`.
