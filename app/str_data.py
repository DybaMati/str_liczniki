"""
Odczyty pod schemat MySQL: sofar_data (PV), licznik_pomiary, licznik_energia.
Liczniki: 7=Tomek, 8=Lonia, 9=Henia.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from math import ceil
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from .db import fetch_all, fetch_one
from .settings import get_settings


def _ids() -> Tuple[int, int, int]:
    s = get_settings()
    return (s.licznik_tomek_id, s.licznik_lonia_id, s.licznik_henia_id)


def _fmt_ts(val: object) -> str:
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    s = str(val)
    if "T" in s and len(s) > 19:
        return s[:19].replace("T", " ")
    return s


def _to_dt(val: object) -> datetime:
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
        ):
            try:
                return datetime.strptime(val[:26].replace("T", " "), fmt)
            except ValueError:
                continue
    raise TypeError(f"nie da się sparsować czasu: {val!r}")


def _range_boundaries(date_from: str, date_to: str) -> Dict[str, str]:
    return {
        "ts_from": f"{date_from} 00:00:01",
        "ts_to": f"{date_to} 23:59:59",
    }


def _fetch_meter_watts_series(licznik_id: int) -> List[Dict[str, Any]]:
    rows = fetch_all(
        text(
            """
            SELECT `timestamp` AS ts, moc_w AS w
            FROM licznik_pomiary
            WHERE licznik_id = :lid
              AND `timestamp` >= (NOW() - INTERVAL 8 HOUR)
            ORDER BY `timestamp` ASC
            """
        ),
        {"lid": licznik_id},
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "ts": _fmt_ts(r.get("ts")),
                "w": float(r.get("w") or 0.0),
            }
        )
    return out


def _fetch_meter_live_card(licznik_id: int, label: str) -> Dict[str, Any]:
    row = fetch_one(
        text(
            """
            SELECT `timestamp` AS ts, moc_w, napiecie_v, prad_a
            FROM licznik_pomiary
            WHERE licznik_id = :lid
            ORDER BY `timestamp` DESC
            LIMIT 1
            """
        ),
        {"lid": licznik_id},
    )
    e_row = fetch_one(
        text(
            """
            SELECT `timestamp` AS ts, energia_kwh
            FROM licznik_energia
            WHERE licznik_id = :lid
            ORDER BY `timestamp` DESC
            LIMIT 1
            """
        ),
        {"lid": licznik_id},
    )
    return {
        "id": licznik_id,
        "label": label,
        "ts": _fmt_ts(row.get("ts")) if row and row.get("ts") else "",
        "wat_w": float(row.get("moc_w") or 0.0) if row else 0.0,
        "voltage_v": float(row.get("napiecie_v") or 0.0) if row else 0.0,
        "amp_a": float(row.get("prad_a") or 0.0) if row else 0.0,
        "kwh": float(e_row.get("energia_kwh") or 0.0) if e_row else 0.0,
        "kwh_ts": _fmt_ts(e_row.get("ts")) if e_row and e_row.get("ts") else "",
        "wat_series": _fetch_meter_watts_series(licznik_id),
    }


def fetch_live() -> Optional[Dict[str, Any]]:
    """Ostatni pomiar PV (sofar) oraz ostatni na każdym liczniku."""
    pv = fetch_one(
        text(
            """
            SELECT `timestamp` AS ts, moc_w AS pv_w
            FROM sofar_data
            ORDER BY `timestamp` DESC
            LIMIT 1
            """
        )
    )
    id1, id2, id3 = _ids()
    q = text(
        """
        SELECT `timestamp` AS ts, moc_w AS w
        FROM licznik_pomiary
        WHERE licznik_id = :lid
        ORDER BY `timestamp` DESC
        LIMIT 1
        """
    )
    m1 = fetch_one(q, {"lid": id1})
    m2 = fetch_one(q, {"lid": id2})
    m3 = fetch_one(q, {"lid": id3})
    if not pv and not (m1 or m2 or m3):
        return None
    times: List[datetime] = []
    if pv and pv.get("ts"):
        times.append(_to_dt(pv["ts"]))
    for m in (m1, m2, m3):
        if m and m.get("ts"):
            times.append(_to_dt(m["ts"]))
    t_show = max(times) if times else datetime.now()
    meter_cards = [
        _fetch_meter_live_card(id1, "Tomek"),
        _fetch_meter_live_card(id2, "Lonia"),
        _fetch_meter_live_card(id3, "Henia"),
    ]
    max_w = 0.0
    for card in meter_cards:
        for pt in card.get("wat_series", []):
            w = float(pt.get("w") or 0.0)
            if w > max_w:
                max_w = w
    # Wspolna skala Y dla porownywalnosci (krok 500W).
    wat_y_max = max(500.0, float(ceil(max_w / 500.0) * 500.0))
    return {
        "ts": t_show,
        "pv_ts": _fmt_ts(pv.get("ts")) if pv and pv.get("ts") else "",
        "l1_ts": _fmt_ts(m1.get("ts")) if m1 and m1.get("ts") else "",
        "l2_ts": _fmt_ts(m2.get("ts")) if m2 and m2.get("ts") else "",
        "l3_ts": _fmt_ts(m3.get("ts")) if m3 and m3.get("ts") else "",
        "pv_w": float(pv["pv_w"]) if pv and pv.get("pv_w") is not None else 0.0,
        "l1_w": float(m1["w"]) if m1 and m1.get("w") is not None else 0.0,
        "l2_w": float(m2["w"]) if m2 and m2.get("w") is not None else 0.0,
        "l3_w": float(m3["w"]) if m3 and m3.get("w") is not None else 0.0,
        "meter_cards": meter_cards,
        "wat_y_max": wat_y_max,
    }


def _last_before(table: str, ts_col: str, val_col: str, before_ts: str) -> Optional[float]:
    row = fetch_one(
        text(
            f"""
            SELECT {val_col} AS v
            FROM {table}
            WHERE {ts_col} < :t
            ORDER BY {ts_col} DESC
            LIMIT 1
            """
        ),
        {"t": before_ts},
    )
    if not row or row.get("v") is None:
        return None
    return float(row["v"])


def _last_meter_before(licznik_id: int, before_ts: str) -> Optional[float]:
    row = fetch_one(
        text(
            """
            SELECT moc_w AS v
            FROM licznik_pomiary
            WHERE licznik_id = :lid AND `timestamp` < :t
            ORDER BY `timestamp` DESC
            LIMIT 1
            """
        ),
        {"lid": licznik_id, "t": before_ts},
    )
    if not row or row.get("v") is None:
        return None
    return float(row["v"])


def fetch_history_merged(date_from: str, date_to: str) -> List[Dict[str, Any]]:
    p = _range_boundaries(date_from, date_to)
    ts_start = p["ts_from"]
    id1, id2, id3 = _ids()

    pv_rows = fetch_all(
        text(
            """
            SELECT `timestamp` AS ts, moc_w AS pv_w
            FROM sofar_data
            WHERE `timestamp` >= :ts_from AND `timestamp` <= :ts_to
            ORDER BY `timestamp` ASC
            """
        ),
        p,
    )
    meter_rows = fetch_all(
        text(
            f"""
            SELECT `timestamp` AS ts, licznik_id, moc_w
            FROM licznik_pomiary
            WHERE licznik_id IN ({id1}, {id2}, {id3})
              AND `timestamp` >= :ts_from AND `timestamp` <= :ts_to
            ORDER BY `timestamp` ASC
            """
        ),
        p,
    )

    init_pv = _last_before("sofar_data", "`timestamp`", "moc_w", ts_start)
    init_l1 = _last_meter_before(id1, ts_start)
    init_l2 = _last_meter_before(id2, ts_start)
    init_l3 = _last_meter_before(id3, ts_start)

    state = {
        "pv_w": init_pv if init_pv is not None else 0.0,
        "l1_w": init_l1 if init_l1 is not None else 0.0,
        "l2_w": init_l2 if init_l2 is not None else 0.0,
        "l3_w": init_l3 if init_l3 is not None else 0.0,
    }

    events: Dict[datetime, Dict[str, float]] = {}
    for r in pv_rows:
        ts = _to_dt(r["ts"])
        if ts not in events:
            events[ts] = {}
        if r.get("pv_w") is not None:
            events[ts]["pv_w"] = float(r["pv_w"])
    for r in meter_rows:
        ts = _to_dt(r["ts"])
        if ts not in events:
            events[ts] = {}
        lid = int(r["licznik_id"])
        v = float(r["moc_w"]) if r.get("moc_w") is not None else 0.0
        if lid == id1:
            events[ts]["l1_w"] = v
        elif lid == id2:
            events[ts]["l2_w"] = v
        elif lid == id3:
            events[ts]["l3_w"] = v

    out: List[Dict[str, Any]] = []
    for ts in sorted(events.keys()):
        ev = events[ts]
        if "pv_w" in ev:
            state["pv_w"] = ev["pv_w"]
        if "l1_w" in ev:
            state["l1_w"] = ev["l1_w"]
        if "l2_w" in ev:
            state["l2_w"] = ev["l2_w"]
        if "l3_w" in ev:
            state["l3_w"] = ev["l3_w"]
        out.append(
            {
                "time": _fmt_ts(ts),
                "pv_w": state["pv_w"],
                "l1_w": state["l1_w"],
                "l2_w": state["l2_w"],
                "l3_w": state["l3_w"],
            }
        )
    return out


def _day_midnight_bounds(day_yyyy_mm_dd: str) -> tuple[str, str]:
    """[dzień 00:00:00, następny dzień 00:00:00) — granice jednej doby kalendarzowej."""
    d = datetime.strptime(day_yyyy_mm_dd, "%Y-%m-%d").date()
    n = d + timedelta(days=1)
    return (f"{d.isoformat()} 00:00:00", f"{n.isoformat()} 00:00:00")


def stmt_meters_kwh_table():
    """Pierwszy odczyt w pierwszym dniu zakresu (od północy); ostatni w ostatnim dniu (przed północą następnego)."""
    id1, id2, id3 = _ids()
    return text(
        f"""
        SELECT ids.licznik_id AS meter_id,
          (
            SELECT e.energia_kwh FROM licznik_energia e
            WHERE e.licznik_id = ids.licznik_id
              AND e.`timestamp` >= :df_start AND e.`timestamp` < :df_end
            ORDER BY e.`timestamp` ASC LIMIT 1
          ) AS start_kwh,
          (
            SELECT e.`timestamp` FROM licznik_energia e
            WHERE e.licznik_id = ids.licznik_id
              AND e.`timestamp` >= :df_start AND e.`timestamp` < :df_end
            ORDER BY e.`timestamp` ASC LIMIT 1
          ) AS start_ts,
          (
            SELECT e.energia_kwh FROM licznik_energia e
            WHERE e.licznik_id = ids.licznik_id
              AND e.`timestamp` >= :dt_start AND e.`timestamp` < :dt_end
            ORDER BY e.`timestamp` DESC LIMIT 1
          ) AS end_kwh,
          (
            SELECT e.`timestamp` FROM licznik_energia e
            WHERE e.licznik_id = ids.licznik_id
              AND e.`timestamp` >= :dt_start AND e.`timestamp` < :dt_end
            ORDER BY e.`timestamp` DESC LIMIT 1
          ) AS end_ts
        FROM (SELECT {id1} AS licznik_id UNION SELECT {id2} UNION SELECT {id3}) AS ids
        """
    )


def fetch_meters_delta(date_from: str, date_to: str) -> List[Dict[str, Any]]:
    """
    Zwraca: pierwszy odczyt kWh pierwszego dnia (po 00:00:00 tego dnia),
    ostatni odczyt ostatniego dnia (ostatni przed 00:00 następnego dnia), różnica.
    """
    df_start, df_end = _day_midnight_bounds(date_from)
    dt_start, dt_end = _day_midnight_bounds(date_to)
    rows = fetch_all(
        stmt_meters_kwh_table(),
        {
            "df_start": df_start,
            "df_end": df_end,
            "dt_start": dt_start,
            "dt_end": dt_end,
        },
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        sk = r.get("start_kwh")
        ek = r.get("end_kwh")
        delta: Optional[float] = None
        if sk is not None and ek is not None:
            delta = float(ek) - float(sk)
        out.append(
            {
                "meter_id": r.get("meter_id"),
                "start_kwh": float(sk) if sk is not None else None,
                "start_ts": _fmt_ts(r.get("start_ts")),
                "end_kwh": float(ek) if ek is not None else None,
                "end_ts": _fmt_ts(r.get("end_ts")),
                "kwh_delta": delta,
            }
        )
    return out
