from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8765

    # Domyślnie MySQL (SCADA); nadpisz w .env — np. inna nazwa bazy lub hasło.
    # SQLite tylko do lokalnego demo: DATABASE_URL=sqlite:///./pv_demo.db
    database_url: str = (
        "mysql+pymysql://SCADA:12345678@10.10.0.21:3306/SOFAR_testy?charset=utf8mb4"
    )

    # ID liczników (schemat str_liczniki / licznik_pomiary, licznik_energia)
    licznik_tomek_id: int = 7
    licznik_lonia_id: int = 8
    licznik_henia_id: int = 9

    # Tabela z mocami chwilowymi (jak w Node-RED: pv_w, l1_w, l2_w, l3_w)
    power_table: str = "power_readings"
    col_ts: str = "ts"
    col_pv: str = "pv_w"
    col_l1: str = "l1_w"
    col_l2: str = "l2_w"
    col_l3: str = "l3_w"

    # Liczniki energii skumulowanej (kWh) — jedna tabela, wiele wierszy wg licznika
    meter_table: str = "meter_readings"
    col_meter_id: str = "meter_id"
    col_meter_ts: str = "ts"
    col_meter_kwh: str = "kwh_total"

    # JSON: {"l1":"Tomek L1","l2":"Lonia L2"} — opcjonalnie nadpisuje domyślne nazwy liczników
    meter_labels_json: Optional[str] = None

    # Nazwa w <title> i w menu (bez „PV” w etykiecie — nadpisz w .env)
    site_public_name: str = "Panel odczytów"

    # Lista dozwolonych IP / CIDR po przecinku, np. 127.0.0.1,192.168.1.0/24,10.10.0.5
    # Puste = brak blokady (wszyscy). Ustawione = tylko pasujace adresy widza aplikacje.
    allowed_client_ips: Optional[str] = None
    # True gdy aplikacja za reverse proxy (nginx) i prawdziwy klient jest w X-Forwarded-For
    trust_x_forwarded_for: bool = False

    denied_page_title: str = "Wejście"
    denied_page_message: str = (
        "Czego tutaj szukasz?? Ciekawość to pierwszy stopień do piekła..."
    )

    # Opcjonalnie: pełne SQL zamiast budowania z powyższych (multiline w .env jest niewygodne — użyj pliku)
    sql_live_file: Optional[str] = None
    sql_history_file: Optional[str] = None
    sql_meters_delta_file: Optional[str] = None


@lru_cache
def get_settings() -> Settings:
    return Settings()


def read_sql_file(path: Optional[str], root: str) -> Optional[str]:
    if not path:
        return None
    full = path if os.path.isabs(path) else os.path.join(root, path)
    if not os.path.isfile(full):
        return None
    with open(full, encoding="utf-8") as f:
        return f.read().strip()
