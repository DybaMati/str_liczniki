"""Zapis FV PDF i indeksu JSON."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .fv_parser import parse_energa_pdf_bytes

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
FV_DIR = DATA_DIR / "fv_do_przeanalizowania"
INDEX_PATH = DATA_DIR / "fv_index.json"


def _ensure_dirs() -> None:
    FV_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> List[Dict[str, Any]]:
    _ensure_dirs()
    if not INDEX_PATH.is_file():
        return []
    try:
        with INDEX_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_index(rows: List[Dict[str, Any]]) -> None:
    _ensure_dirs()
    with INDEX_PATH.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def _safe_filename(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^\w.\-ąćęłńóśźżĄĆĘŁŃÓŚŹŻ ]", "_", base, flags=re.I)
    return base[:120] or "faktura.pdf"


def list_invoices() -> List[Dict[str, Any]]:
    rows = _load_index()
    out = []
    for r in sorted(rows, key=lambda x: x.get("uploaded_at", ""), reverse=True):
        out.append(
            {
                "id": r.get("id"),
                "original_name": r.get("original_name"),
                "uploaded_at": r.get("uploaded_at"),
                "nr_faktury": (r.get("parsed") or {}).get("nr_faktury"),
                "okres_od": (r.get("parsed") or {}).get("okres_od"),
                "okres_do": (r.get("parsed") or {}).get("okres_do"),
                "do_zaplaty": ((r.get("parsed") or {}).get("podsumowanie") or {}).get(
                    "do_zaplaty_brutto"
                ),
            }
        )
    return out


def get_invoice(inv_id: str) -> Optional[Dict[str, Any]]:
    for r in _load_index():
        if r.get("id") == inv_id:
            return r
    return None


def pdf_path(inv_id: str) -> Optional[Path]:
    row = get_invoice(inv_id)
    if not row:
        return None
    p = FV_DIR / row.get("stored_name", "")
    return p if p.is_file() else None


def delete_invoice(inv_id: str) -> bool:
    """Usuwa FV z indeksu i plik PDF z dysku."""
    if not inv_id or not re.match(r"^[a-f0-9]{8,32}$", inv_id):
        return False
    rows = _load_index()
    kept: List[Dict[str, Any]] = []
    removed: Optional[Dict[str, Any]] = None
    for r in rows:
        if r.get("id") == inv_id:
            removed = r
        else:
            kept.append(r)
    if removed is None:
        return False
    _save_index(kept)
    stored = removed.get("stored_name") or ""
    if stored:
        p = FV_DIR / stored
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass
    return True


def compute_split(
    parsed: Dict[str, Any],
    meters: List[Dict[str, Any]],
    labels: Dict[str, str],
    fixed_split: str = "kwh",
) -> Dict[str, Any]:
    """Podział stałych i zmiennych netto między liczniki wg zużycia kWh w okresie."""
    pod = parsed.get("podsumowanie") or {}
    stala = float(pod.get("stala_netto") or 0)
    zmienna = float(pod.get("zmienna_netto") or 0)

    items: List[Dict[str, Any]] = []
    total_kwh = 0.0
    for m in meters:
        kwh = m.get("kwh")
        if kwh is not None:
            total_kwh += float(kwh)

    n = len(meters) or 1
    rows: List[Dict[str, Any]] = []
    for m in meters:
        mid = str(m.get("meter_id", ""))
        kwh = m.get("kwh")
        kwh_f = float(kwh) if kwh is not None else 0.0
        if fixed_split == "rowno":
            share = 1.0 / n
        elif total_kwh > 0 and kwh is not None:
            share = kwh_f / total_kwh
        else:
            share = 1.0 / n

        stala_part = round(stala * share, 2)
        zmienna_part = round(zmienna * share, 2)
        razem_netto = round(stala_part + zmienna_part, 2)
        vat_pct = int(pod.get("vat_pct") or 23)
        razem_brutto = round(razem_netto * (1 + vat_pct / 100), 2)

        rows.append(
            {
                "meter_id": mid,
                "label": m.get("label") or labels.get(mid, mid),
                "kwh": kwh,
                "udzial_pct": round(share * 100, 1) if total_kwh > 0 else round(100 / n, 1),
                "stala_netto": stala_part,
                "zmienna_netto": zmienna_part,
                "razem_netto": razem_netto,
                "razem_brutto": razem_brutto,
            }
        )

    return {
        "okres_od_iso": parsed.get("okres_od_iso"),
        "okres_do_iso": parsed.get("okres_do_iso"),
        "kwh_fv": parsed.get("kwh_rozliczeniowe"),
        "kwh_liczniki_suma": round(total_kwh, 3),
        "stala_netto_total": stala,
        "zmienna_netto_total": zmienna,
        "fixed_split_mode": fixed_split,
        "meters": rows,
    }


def save_upload(
    filename: str,
    pdf_bytes: bytes,
    meters_delta_fn,
    meter_labels: Dict[str, str],
) -> Dict[str, Any]:
    _ensure_dirs()
    inv_id = uuid.uuid4().hex[:12]
    safe = _safe_filename(filename)
    stored = f"{inv_id}_{safe}"
    path = FV_DIR / stored
    path.write_bytes(pdf_bytes)

    parsed = parse_energa_pdf_bytes(pdf_bytes)
    split: Optional[Dict[str, Any]] = None
    split_error: Optional[str] = None

    if parsed.get("ok") and parsed.get("okres_od_iso") and parsed.get("okres_do_iso"):
        try:
            raw_meters = meters_delta_fn(parsed["okres_od_iso"], parsed["okres_do_iso"])
            items = []
            for r in raw_meters:
                mid = str(r.get("meter_id", ""))
                items.append(
                    {
                        "meter_id": mid,
                        "label": meter_labels.get(mid, mid),
                        "kwh": r.get("kwh_delta"),
                    }
                )
            split = compute_split(parsed, items, meter_labels)
        except Exception as e:
            split_error = str(e)
    elif parsed.get("ok"):
        split_error = "Brak dat okresu — nie można pobrać zużycia liczników."

    row = {
        "id": inv_id,
        "original_name": filename,
        "stored_name": stored,
        "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "parsed": parsed,
        "split": split,
        "split_error": split_error,
    }
    rows = _load_index()
    rows.append(row)
    _save_index(rows)
    return row
