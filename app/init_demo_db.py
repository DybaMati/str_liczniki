"""
Tworzy sqlite pv_demo.db z przykładowymi tabelami i danymi (do testów lokalnych).
Uruchom: python -m app.init_demo_db
"""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from .db import get_engine, reset_engine
from .settings import get_settings


def ensure_sqlite():
    s = get_settings()
    if not s.database_url.startswith("sqlite"):
        raise SystemExit(
            "init_demo_db działa tylko dla SQLite — ustaw DATABASE_URL=sqlite:///./pv_demo.db w .env"
        )


def create_schema(conn) -> None:
    s = get_settings()
    conn.execute(
        text(
            f"""
        CREATE TABLE IF NOT EXISTS {s.power_table} (
            {s.col_ts} TEXT NOT NULL,
            {s.col_pv} REAL NOT NULL DEFAULT 0,
            {s.col_l1} REAL NOT NULL DEFAULT 0,
            {s.col_l2} REAL NOT NULL DEFAULT 0,
            {s.col_l3} REAL NOT NULL DEFAULT 0
        );
        """
        )
    )
    conn.execute(
        text(
            f"""
        CREATE TABLE IF NOT EXISTS {s.meter_table} (
            {s.col_meter_id} TEXT NOT NULL,
            {s.col_meter_ts} TEXT NOT NULL,
            {s.col_meter_kwh} REAL NOT NULL
        );
        """
        )
    )


def seed(conn) -> None:
    s = get_settings()
    conn.execute(text(f"DELETE FROM {s.power_table}"))
    conn.execute(text(f"DELETE FROM {s.meter_table}"))
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    pts = []
    for i in range(96):
        t = start + timedelta(minutes=15 * i)
        ts = t.strftime("%Y-%m-%dT%H:%M:%S")
        hour = t.hour + t.minute / 60.0
        sun = max(0, min(1, 1 - abs(hour - 12) / 7))
        pv = 3000 * sun + random.random() * 200
        l1 = 200 + random.random() * 400
        l2 = 150 + random.random() * 300
        l3 = 180 + random.random() * 350
        pts.append({"ts": ts, "pv": pv, "l1": l1, "l2": l2, "l3": l3})

    ins = text(
        f"""
        INSERT INTO {s.power_table} ({s.col_ts}, {s.col_pv}, {s.col_l1}, {s.col_l2}, {s.col_l3})
        VALUES (:ts, :pv, :l1, :l2, :l3)
        """
    )
    for p in pts:
        conn.execute(ins, p)

    meters = ["l1", "l2", "l3"]
    base = {m: 1000.0 * (i + 1) for i, m in enumerate(meters)}
    days_ago = 14
    for d in range(days_ago, -1, -1):
        day = datetime.now(UTC).date() - timedelta(days=d)
        for m in meters:
            base[m] += random.random() * 8 + 2
            ts = f"{day.isoformat()}T23:50:00"
            conn.execute(
                text(
                    f"""
                    INSERT INTO {s.meter_table} ({s.col_meter_id}, {s.col_meter_ts}, {s.col_meter_kwh})
                    VALUES (:mid, :ts, :kwh)
                    """
                ),
                {"mid": m, "ts": ts, "kwh": base[m]},
            )


def main():
    ensure_sqlite()
    reset_engine()
    e = get_engine()
    with e.begin() as conn:
        create_schema(conn)
        seed(conn)
    print(f"Utworzono / zasilono bazę: {get_settings().database_url}")


if __name__ == "__main__":
    main()
