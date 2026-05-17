"""Parser faktur ENERGA-OBRÓT (tekst z PDF)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# MC = opłata miesięczna (stała); kWh/MWh = zmienna
_FIXED_UNITS = frozenset({"MC"})
_VARIABLE_UNITS = frozenset({"KWH", "MWH"})


def _pl_money(s: str) -> float:
    return float(s.strip().replace(" ", "").replace(",", "."))


def _pl_date_to_iso(s: str) -> str:
    d = datetime.strptime(s.strip(), "%d.%m.%Y")
    return d.strftime("%Y-%m-%d")


def _charge_kind(unit: str, name: str) -> str:
    u = unit.upper()
    if u in _FIXED_UNITS:
        return "stala"
    if u in _VARIABLE_UNITS:
        return "zmienna"
    n = name.lower()
    if "stała" in n or "stała" in n.replace("ł", "l"):
        return "stala"
    if "mocowa" in n or "abonament" in n or "handlowa" in n:
        return "stala"
    return "zmienna"


def _parse_line_item(line: str) -> Optional[Dict[str, Any]]:
    m = re.match(
        r"^(.+?)\s+"
        r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})\s+"
        r"([\d,]+)\s+(\S+)\s+"
        r"([\d,]+)\s+"
        r"([\d,]+)\s+"
        r"(\d+)\s*$",
        line.strip(),
    )
    if not m:
        return None
    name, d_from, d_to, qty_s, unit, price_s, net_s, vat = m.groups()
    unit_u = unit.upper()
    if unit_u == "KWH":
        unit_u = "kWh"
    elif unit_u == "MWH":
        unit_u = "MWh"
    kind = _charge_kind(unit_u, name)
    return {
        "nazwa": name.strip(),
        "od": d_from,
        "do": d_to,
        "ilosc": _pl_money(qty_s),
        "jm": unit_u if unit_u not in ("KWH", "MWH") else ("kWh" if unit_u == "KWH" else "MWh"),
        "cena_netto": _pl_money(price_s),
        "wartosc_netto": _pl_money(net_s),
        "vat_pct": int(vat),
        "rodzaj": kind,
    }


def parse_energa_pdf_text(text: str) -> Dict[str, Any]:
    """Zwraca strukturę jak na FV + podsumowania stałe/zmienne."""
    errors: List[str] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    period_m = re.search(
        r"Rozliczenie za okres\s+(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})",
        text,
    )
    period_from = period_to = period_from_iso = period_to_iso = ""
    if period_m:
        period_from, period_to = period_m.group(1), period_m.group(2)
        period_from_iso = _pl_date_to_iso(period_from)
        period_to_iso = _pl_date_to_iso(period_to)
    else:
        errors.append("Nie znaleziono okresu rozliczenia na FV.")

    inv_m = re.search(r"Faktura VAT\s+(\S+)", text)
    nr_faktury = inv_m.group(1) if inv_m else ""

    nr_klienta_m = re.search(r"NR KLIENTA:\s*(\d+)", text)
    nr_klienta = nr_klienta_m.group(1) if nr_klienta_m else ""

    sprzedaz: List[Dict[str, Any]] = []
    dystrybucja: List[Dict[str, Any]] = []
    section: Optional[str] = None

    for line in lines:
        if "1. ROZLICZENIE SPRZEDAŻY" in line:
            section = "sprzedaz"
            continue
        if "2. ROZLICZENIE DYSTRYBUCJI" in line:
            section = "dystrybucja"
            continue
        if line.startswith("3. ROZLICZENIE") or line.startswith("Razem wartość netto"):
            section = None
        item = _parse_line_item(line)
        if item and section == "sprzedaz":
            sprzedaz.append(item)
        elif item and section == "dystrybucja":
            dystrybucja.append(item)

    kwh_m = re.search(
        r"Suma godzinowych sald dodatnich\s+\d{2}\.\d{2}\.\d{4}\s+\d{2}\.\d{2}\.\d{4}\s+(\d+)",
        text,
    )
    kwh_rozliczeniowe = int(kwh_m.group(1)) if kwh_m else None
    if kwh_rozliczeniowe is None:
        for it in sprzedaz + dystrybucja:
            if it.get("jm") == "kWh" and it.get("ilosc"):
                kwh_rozliczeniowe = int(it["ilosc"])
                break

    def _find_money(pattern: str) -> Optional[float]:
        m = re.search(pattern, text, re.I)
        if not m:
            return None
        return _pl_money(m.group(1))

    wartosc_brutto = _find_money(r"Rozliczenie energii elektrycznej i świadczenia usługi dystrybucji\s+([\d,]+)")
    if wartosc_brutto is None:
        wartosc_brutto = _find_money(r"Razem:\s*([\d,]+)\s*zł")
    netto_razem_m = re.search(r"Razem wartość netto \(1 \+ 2\)\s+([\d,]+)", text)
    netto_razem = _pl_money(netto_razem_m.group(1)) if netto_razem_m else None

    vat_m = re.search(
        r"Rozliczenie energii elektrycznej i świadczenia usługi dystrybucji\s+[\d,]+\s+([\d,]+)\s+([\d,]+)",
        text,
    )
    kwota_vat = _pl_money(vat_m.group(1)) if vat_m else None
    if wartosc_brutto is None and vat_m:
        wartosc_brutto = _pl_money(vat_m.group(2))

    depozyt = _find_money(r"Pobrano z DEPOZYTU\s+([\d,]+)")
    do_zaplaty = _find_money(r"Wartość do zapłaty\s*\n\s*([\d,]+)")
    if do_zaplaty is None:
        do_zaplaty = _find_money(r"Kwota płatności:\s*([\d,]+)")

    wartosc_pobrana = _find_money(r"wartość energii pobranej\s+([\d,]+)")

    all_items = sprzedaz + dystrybucja
    stala_netto = sum(i["wartosc_netto"] for i in all_items if i["rodzaj"] == "stala")
    zmienna_netto = sum(i["wartosc_netto"] for i in all_items if i["rodzaj"] == "zmienna")
    if netto_razem is None and all_items:
        netto_razem = round(stala_netto + zmienna_netto, 2)

    vat_pct = 23
    if all_items:
        vat_pct = all_items[0].get("vat_pct", 23)

    if kwota_vat is None and netto_razem is not None:
        kwota_vat = round(netto_razem * vat_pct / 100, 2)
    if wartosc_brutto is None and netto_razem is not None and kwota_vat is not None:
        wartosc_brutto = round(netto_razem + kwota_vat, 2)

    ok = bool(period_from and all_items)
    return {
        "ok": ok,
        "dostawca": "ENERGA",
        "errors": errors,
        "nr_faktury": nr_faktury,
        "nr_klienta": nr_klienta,
        "okres_od": period_from,
        "okres_do": period_to,
        "okres_od_iso": period_from_iso,
        "okres_do_iso": period_to_iso,
        "kwh_rozliczeniowe": kwh_rozliczeniowe,
        "sprzedaz": sprzedaz,
        "dystrybucja": dystrybucja,
        "podsumowanie": {
            "stala_netto": round(stala_netto, 2),
            "zmienna_netto": round(zmienna_netto, 2),
            "razem_netto": netto_razem,
            "vat_pct": vat_pct,
            "kwota_vat": kwota_vat,
            "razem_brutto": wartosc_brutto,
            "wartosc_energii_pobranej_brutto": wartosc_pobrana,
            "depozyt_brutto": depozyt,
            "do_zaplaty_brutto": do_zaplaty,
        },
    }


def extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError("Brak pypdf — zainstaluj: pip install pypdf") from e

    import io

    parts: List[str] = []
    reader = PdfReader(io.BytesIO(pdf_bytes))
    for page in reader.pages:
        t = page.extract_text() or ""
        if t.strip():
            parts.append(t)
    return "\n".join(parts)


def parse_energa_pdf_bytes(pdf_bytes: bytes) -> Dict[str, Any]:
    text = extract_pdf_text(pdf_bytes)
    if not text.strip():
        return {"ok": False, "errors": ["PDF bez tekstu (skan?) — na razie obsługujemy FV z warstwą tekstową."]}
    out = parse_energa_pdf_text(text)
    out["raw_text_len"] = len(text)
    return out
