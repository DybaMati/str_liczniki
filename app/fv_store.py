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


def _summary_from_parsed(parsed: Dict[str, Any]) -> Dict[str, Any]:
    pod = parsed.get("podsumowanie") or {}
    return {
        "nr_faktury": parsed.get("nr_faktury"),
        "okres_od": parsed.get("okres_od"),
        "okres_do": parsed.get("okres_do"),
        "do_zaplaty": pod.get("do_zaplaty_brutto"),
    }


def _read_pdf_bytes(row: Dict[str, Any]) -> Optional[bytes]:
    stored = row.get("stored_name") or ""
    if not stored:
        return None
    p = FV_DIR / stored
    if not p.is_file():
        return None
    return p.read_bytes()


def compute_invoice(
    row: Dict[str, Any],
    meters_delta_fn,
    meter_labels: Dict[str, str],
    pv_delta_fn=None,
) -> Dict[str, Any]:
    """PDF → parse → liczniki L1–L3 + PV z bazy → podział (za każdym razem na świeżo)."""
    pdf_bytes = _read_pdf_bytes(row)
    if not pdf_bytes:
        return {
            **row,
            "parsed": {"ok": False, "errors": ["Brak pliku PDF na dysku."]},
            "split": None,
            "split_error": "Brak pliku PDF",
            "comparison": None,
            "meter_readings": [],
        }

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

    summary = _summary_from_parsed(parsed)
    return {
        "id": row.get("id"),
        "original_name": row.get("original_name"),
        "uploaded_at": row.get("uploaded_at"),
        "nr_faktury": summary.get("nr_faktury"),
        "okres_od": summary.get("okres_od"),
        "okres_do": summary.get("okres_do"),
        "do_zaplaty": summary.get("do_zaplaty"),
        "parsed": parsed,
        "split": split,
        "split_error": split_error,
        "comparison": comparison,
        "meter_readings": meter_items,
    }


def list_invoices() -> List[Dict[str, Any]]:
    rows = _load_index()
    out = []
    for r in sorted(rows, key=lambda x: x.get("uploaded_at", ""), reverse=True):
        item = {
            "id": r.get("id"),
            "original_name": r.get("original_name"),
            "uploaded_at": r.get("uploaded_at"),
            "nr_faktury": r.get("nr_faktury"),
            "okres_od": r.get("okres_od"),
            "okres_do": r.get("okres_do"),
            "do_zaplaty": r.get("do_zaplaty"),
        }
        if not item["nr_faktury"]:
            pdf_bytes = _read_pdf_bytes(r)
            if pdf_bytes:
                item.update(_summary_from_parsed(parse_energa_pdf_bytes(pdf_bytes)))
        out.append(item)
    return out


def get_invoice(
    inv_id: str,
    meters_delta_fn=None,
    meter_labels: Optional[Dict[str, str]] = None,
    pv_delta_fn=None,
) -> Optional[Dict[str, Any]]:
    row = _get_index_row(inv_id)
    if not row:
        return None
    if meters_delta_fn and meter_labels is not None:
        return compute_invoice(row, meters_delta_fn, meter_labels, pv_delta_fn)
    return row


def _get_index_row(inv_id: str) -> Optional[Dict[str, Any]]:
    for r in _load_index():
        if r.get("id") == inv_id:
            return r
    return None


def pdf_path(inv_id: str) -> Optional[Path]:
    row = _get_index_row(inv_id)
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
    vat_pct = int(pod.get("vat_pct") or 23)
    razem_brutto_fv = float(pod.get("razem_brutto") or 0)
    kwota_vat_fv = float(pod.get("kwota_vat") or 0)
    do_zaplaty_total = pod.get("do_zaplaty_brutto")
    do_zaplaty_f = float(do_zaplaty_total) if do_zaplaty_total is not None else None
    ratio_pay = (
        do_zaplaty_f / razem_brutto_fv
        if do_zaplaty_f is not None and razem_brutto_fv > 0
        else 1.0
    )
    rows: List[Dict[str, Any]] = []
    do_zaplaty_assigned = 0.0
    sum_stala_platne = 0.0
    sum_zmienna_platne = 0.0
    sum_vat_platne = 0.0
    for mi, m in enumerate(meters):
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
        razem_brutto = round(razem_netto * (1 + vat_pct / 100), 2)
        do_zaplaty_part: Optional[float] = None
        stala_platne: Optional[float] = None
        zmienna_platne: Optional[float] = None
        vat_platne: Optional[float] = None
        if do_zaplaty_f is not None:
            if mi == len(meters) - 1:
                do_zaplaty_part = round(do_zaplaty_f - do_zaplaty_assigned, 2)
            else:
                do_zaplaty_part = round(do_zaplaty_f * share, 2)
                do_zaplaty_assigned += do_zaplaty_part
            row_netto_platne = round(do_zaplaty_part / (1 + vat_pct / 100), 2)
            if razem_netto > 0:
                stala_platne = round(row_netto_platne * (stala_part / razem_netto), 2)
            else:
                stala_platne = round(row_netto_platne / max(n, 1), 2)
            zmienna_platne = round(row_netto_platne - stala_platne, 2)
            vat_platne = round(do_zaplaty_part - stala_platne - zmienna_platne, 2)
            sum_stala_platne += stala_platne
            sum_zmienna_platne += zmienna_platne
            sum_vat_platne += vat_platne

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
                "stala_platne": stala_platne,
                "zmienna_platne": zmienna_platne,
                "vat_platne": vat_platne,
                "do_zaplaty_brutto": do_zaplaty_part,
            }
        )

    exp_stala = round(stala * ratio_pay, 2)
    exp_zmienna = round(zmienna * ratio_pay, 2)
    exp_vat = (
        round((do_zaplaty_f or 0) - exp_stala - exp_zmienna, 2)
        if do_zaplaty_f is not None
        else round(kwota_vat_fv * ratio_pay, 2)
    )
    exp_razem = round(do_zaplaty_f, 2) if do_zaplaty_f is not None else None
    tol = 0.03

    def _ok(a: float, b: Optional[float]) -> bool:
        if b is None:
            return True
        return abs(a - b) <= tol

    checksum = {
        "sum_stala_platne": round(sum_stala_platne, 2),
        "sum_zmienna_platne": round(sum_zmienna_platne, 2),
        "sum_vat_platne": round(sum_vat_platne, 2),
        "sum_razem_platne": round(do_zaplaty_f, 2) if do_zaplaty_f is not None else 0.0,
        "expected_stala_platne": exp_stala,
        "expected_zmienna_platne": exp_zmienna,
        "expected_vat_platne": exp_vat,
        "expected_razem_platne": exp_razem,
        "stala_ok": _ok(sum_stala_platne, exp_stala),
        "zmienna_ok": _ok(sum_zmienna_platne, exp_zmienna),
        "vat_ok": _ok(sum_vat_platne, exp_vat),
        "razem_ok": _ok(do_zaplaty_f or 0, exp_razem),
        "all_ok": (
            _ok(sum_stala_platne, exp_stala)
            and _ok(sum_zmienna_platne, exp_zmienna)
            and _ok(sum_vat_platne, exp_vat)
            and _ok(do_zaplaty_f or 0, exp_razem)
        ),
    }

    return {
        "okres_od_iso": parsed.get("okres_od_iso"),
        "okres_do_iso": parsed.get("okres_do_iso"),
        "kwh_fv": parsed.get("kwh_rozliczeniowe"),
        "kwh_liczniki_suma": round(total_kwh, 3),
        "stala_netto_total": stala,
        "zmienna_netto_total": zmienna,
        "do_zaplaty_total": do_zaplaty_f,
        "razem_brutto_fv": pod.get("razem_brutto"),
        "ratio_platne": round(ratio_pay, 6) if do_zaplaty_f is not None else None,
        "checksum": checksum,
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
    """Zapisuje tylko PDF + wpis w indeksie; obliczenia przy odczycie FV."""
    _ensure_dirs()
    inv_id = uuid.uuid4().hex[:12]
    safe = _safe_filename(filename)
    stored = f"{inv_id}_{safe}"
    path = FV_DIR / stored
    path.write_bytes(pdf_bytes)

    parsed = parse_energa_pdf_bytes(pdf_bytes)
    summary = _summary_from_parsed(parsed)
    row = {
        "id": inv_id,
        "original_name": filename,
        "stored_name": stored,
        "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        **summary,
    }
    rows = _load_index()
    rows.append(row)
    _save_index(rows)
    return compute_invoice(row, meters_delta_fn, meter_labels, pv_delta_fn)
