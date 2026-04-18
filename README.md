# str_liczniki — dashboard WWW (FastAPI)

Dashboard odczytu: **PV** z tabeli `sofar_data`, mocy **L1–L3** z `licznik_pomiary` (liczniki 7 / 8 / 9), oraz **zużycia kWh** z `licznik_energia`.

## Wymagania

- Python 3.11+
- MySQL z tabelami zgodnymi ze schematem (patrz `app/str_data.py`)

## Instalacja

```bash
pip install -r requirements.txt
copy .env.example .env
```

W pliku `.env` ustaw `DATABASE_URL` i ewentualnie port. **Nie commituj `.env`** (jest w `.gitignore`).

## Uruchomienie

```bash
python run.py
```

Domyślnie: `http://0.0.0.0:8765` — strony: `/live`, `/chart`, `/meters`.

## Demo SQLite (bez MySQL)

```bash
python -m app.init_demo_db
# DATABASE_URL=sqlite:///./pv_demo.db w .env
python run.py
```

## Schemat bazy (MySQL)

- `sofar_data` — PV: `timestamp`, `moc_w`
- `licznik_pomiary` — `timestamp`, `licznik_id`, `moc_w`
- `licznik_energia` — `timestamp`, `licznik_id`, `energia_kwh` (skumulowane kWh)

ID liczników domyślnie: **7** Tomek, **8** Lonia, **9** Henia — zmiana przez `LICZNIK_*_ID` w `.env`.
