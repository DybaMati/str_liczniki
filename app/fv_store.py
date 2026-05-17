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


def build_comparison(
    parsed: Dict[str, Any],
    meters: List[Dict[str, Any]],
    pv_range: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Porównanie odczytów z FV z licznikami wewnętrznymi i produkcją PV."""
    de = parsed.get("dane_energii") or {}
    pob = de.get("pobranie") or {}
    wpr = de.get("wprowadzenie") or {}
    saldo_dod = de.get("saldo_dodatnie") or {}
    saldo_ujem = de.get("saldo_ujemne") or {}

    fv_roz = parsed.get("kwh_rozliczeniowe")
    fv_pob_licznik = pob.get("ilosc_kwh")
    fv_wpr_licznik = wpr.get("ilosc_kwh")
    fv_saldo_dod = saldo_dod.get("kwh")
    fv_saldo_ujem = saldo_ujem.get("kwh")

    sum_liczniki = 0.0
    for m in meters:
        if m.get("kwh") is not None:
            sum_liczniki += float(m["kwh"])

    pv_kwh = None
    if pv_range and pv_range.get("kwh_delta") is not None:
        pv_kwh = float(pv_range["kwh_delta"])

    def _diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
        if a is None or b is None:
            return None
        return round(float(b) - float(a), 3)

    return {
        "fv_kwh_rozliczone": fv_roz,
        "fv_kwh_pobranie_licznik": fv_pob_licznik,
        "fv_kwh_wprowadzenie_licznik": fv_wpr_licznik,
        "fv_saldo_dodatnie_kwh": fv_saldo_dod,
        "fv_saldo_ujemne_kwh": fv_saldo_ujem,
        "liczniki_wewn_suma_kwh": round(sum_liczniki, 3) if sum_liczniki else None,
        "pv_produkcja_kwh": pv_kwh,
        "roznica_liczniki_minus_fv_rozliczone": _diff(fv_roz, sum_liczniki if sum_liczniki else None),
        "roznica_pv_minus_wprowadzenie_fv": _diff(fv_wpr_licznik, pv_kwh),
        "uwagi": _comparison_notes(
            fv_roz, fv_pob_licznik, fv_wpr_licznik, sum_liczniki, pv_kwh
        ),
    }


def _comparison_notes(
    fv_roz: Optional[int],
    fv_pob: Optional[float],
    fv_wpr: Optional[float],
    sum_liczniki: float,
    pv_kwh: Optional[float],
) -> List[str]:
    notes: List[str] = []
    if fv_roz is not None and sum_liczniki > 0:
        diff = round(sum_liczniki - fv_roz, 1)
        if abs(diff) > 5:
            notes.append(
                f"Suma 3 liczników ({sum_liczniki:.1f} kWh) vs kWh rozliczone na FV ({fv_roz}): różnica {diff:+.1f} kWh."
            )
    if fv_pob is not None and fv_roz is not None and abs(fv_pob - fv_roz) > 1:
        notes.append(
            f"Odczyt licznika głównego pobranie ({fv_pob:.3f} kWh) vs saldo dodatnie do rozliczenia ({fv_roz} kWh) — na FV po bilansie prosumenta."
        )
    if pv_kwh is not None and fv_wpr is not None:
        diff = round(pv_kwh - fv_wpr, 1)
        if abs(diff) > 10:
            notes.append(
                f"Produkcja PV z bazy ({pv_kwh:.1f} kWh) vs wprowadzenie na FV ({fv_wpr:.1f} kWh): różnica {diff:+.1f} kWh."
            )
    if not notes:
        notes.append("Wartości są blisko siebie lub brak danych do porównania w tym okresie.")
    return notes


def save_upload(
    filename: str,
    pdf_bytes: bytes,
    meters_delta_fn,
    meter_labels: Dict[str, str],
    pv_delta_fn=None,
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
    comparison: Optional[Dict[str, Any]] = None
    meter_items: List[Dict[str, Any]] = []

    if parsed.get("ok") and parsed.get("okres_od_iso") and parsed.get("okres_do_iso"):
        try:
            raw_meters = meters_delta_fn(parsed["okres_od_iso"], parsed["okres_do_iso"])
            for r in raw_meters:
                mid = str(r.get("meter_id", ""))
                meter_items.append(
                    {
                        "meter_id": mid,
                        "label": meter_labels.get(mid, mid),
                        "kwh": r.get("kwh_delta"),
                        "start_kwh": r.get("start_kwh"),
                        "end_kwh": r.get("end_kwh"),
                        "start_ts": r.get("start_ts"),
                        "end_ts": r.get("end_ts"),
                    }
                )
            split = compute_split(parsed, meter_items, meter_labels)
            pv_range = None
            if pv_delta_fn:
                try:
                    pv_range = pv_delta_fn(parsed["okres_od_iso"], parsed["okres_do_iso"])
                except Exception:
                    pv_range = None
            comparison = build_comparison(parsed, meter_items, pv_range)
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
        "comparison": comparison,
        "meter_readings": meter_items,
    }
    rows = _load_index()
    rows.append(row)
    _save_index(rows)
    return row
