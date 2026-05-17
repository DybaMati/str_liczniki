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


def _pl_num(s: str) -> float:
    return float(s.strip().replace(" ", "").replace(",", "."))


def _norm_line(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


# Wskazania: „10 652,43” lub „10 563,167” (PDF bywa z 2 lub 3 miejscami po przecinku)
_WSK_PL_RE = re.compile(
    r"\d{1,2}(?: \d{3})+,\d{2,3}|\d{1,3}(?: \d{3})*,\d{2,3}|\d+,\d{2,3}"
)
_ILOSC_KWH_RE = re.compile(
    r"^(\d{1,3}(?: \d{3})*,\d{1,3}|\d{1,3}(?: \d{3})*,\d{2,3}|\d{1,3} \d{3}|\d+,\d{1,3})"
)
_METER_HEAD_RE = re.compile(
    r"G(\d+)\s+(\d+)\s+(\w)\s+"
    r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})\s+"
    r"(.+?)\s+([A-Z])(?:\s+\d+)?\s*$",
    re.I,
)


def _pl_num_ilosc(s: str) -> float:
    """Ilość kWh: 260,325 albo z PDF czasem '260 325' (= 260,325). Bez spacji przy przecinku."""
    s = _norm_line(s)
    if "," in s:
        return _pl_num(s)
    m = re.match(r"^(\d{1,3}) (\d{3})$", s)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    return _pl_num(s)


def _kwh_from_wskazania(wsk_od: float, wsk_do: float) -> float:
    return round(max(0.0, wsk_do - wsk_od), 3)


def _pick_ilosc_kwh(wsk_od: float, wsk_do: float, raw: Optional[float]) -> float:
    """Zużycie: różnica wskazań; popraw tylko zlepki z PDF (np. „5 260,325” → 5260)."""
    delta = _kwh_from_wskazania(wsk_od, wsk_do)
    if raw is None or raw <= 0:
        return delta
    if raw > 5000 and delta < 2000:
        return delta
    if abs(raw - delta) > max(50.0, delta * 0.5):
        return delta
    return round(raw, 3)


def _parse_ilosc_from_rest(rest: str) -> Optional[float]:
    rest = rest.strip()
    m = _ILOSC_KWH_RE.match(rest)
    if not m:
        return None
    return _pl_num_ilosc(m.group(1))


def _parse_meter_tail(tail: str) -> Optional[Tuple[float, float, float, str]]:
    wsk = list(_WSK_PL_RE.finditer(tail))
    if len(wsk) >= 2:
        wsk_od = _pl_num(wsk[0].group(0))
        wsk_do = _pl_num(wsk[1].group(0))
        rest = tail[wsk[1].end() :].strip()
        raw_ilosc = _parse_ilosc_from_rest(rest)
        ilosc = _pick_ilosc_kwh(wsk_od, wsk_do, raw_ilosc)
        rodzaj = "Z"
        rm = re.search(r"\b([A-Z])\s*$", rest)
        if rm:
            rodzaj = rm.group(1).upper()
        return wsk_od, wsk_do, ilosc, rodzaj
    tokens = re.findall(
        r"\d{1,2}(?: \d{3})+,\d{2,3}|\d{1,3}(?: \d{3})*,\d{2,3}|\d+,\d{2,3}",
        tail,
    )
    if len(tokens) >= 2:
        wsk_od = _pl_num(tokens[0])
        wsk_do = _pl_num(tokens[1])
        rest = tail
        for t in tokens[:2]:
            idx = rest.find(t)
            if idx >= 0:
                rest = rest[idx + len(t) :]
        raw_ilosc = _parse_ilosc_from_rest(rest.strip())
        ilosc = _pick_ilosc_kwh(wsk_od, wsk_do, raw_ilosc)
        return wsk_od, wsk_do, ilosc, "Z"
    return None


def _parse_meter_line(line: str) -> Optional[Dict[str, Any]]:
    """Linia G11 … wsk_od wsk_do ilosc Z — poprawnie ze spacjami w tysiącach."""
    m = _METER_HEAD_RE.match(_norm_line(line))
    if not m:
        return None
    parsed_tail = _parse_meter_tail(m.group(6))
    if not parsed_tail:
        return None
    wsk_od, wsk_do, ilosc, rodzaj = parsed_tail
    return {
        "grupa_taryfowa": f"G{m.group(1)}",
        "nr_licznika": m.group(2),
        "strefa": m.group(3).upper(),
        "data_odczytu_od": m.group(4),
        "data_odczytu_do": m.group(5),
        "wskazanie_od": wsk_od,
        "wskazanie_do": wsk_do,
        "ilosc_kwh": ilosc,
        "rodzaj_odczytu": rodzaj if len(rodzaj) == 1 else m.group(7).upper(),
    }


def _find_meter_after_markers(text: str, markers: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
    """Szuka linii licznika po nagłówku sekcji (PDF bywa rozbity na wiele linii)."""
    upper = text.upper()
    for marker in markers:
        idx = upper.find(marker.upper())
        if idx < 0:
            continue
        chunk = _norm_line(text[idx : idx + 1200])
        m = _METER_HEAD_RE.search(chunk)
        if m:
            parsed = _parse_meter_line(m.group(0))
            if parsed:
                return parsed
    return None


def _line_after_marker(lines: List[str], marker: str, predicate) -> Optional[str]:
    found = False
    for ln in lines:
        if marker in ln:
            found = True
            continue
        if not found:
            continue
        if predicate(ln):
            return ln.strip()
        if ln.startswith("1. ROZLICZENIE") or ln.startswith("2. ROZLICZENIE"):
            break
    return None


def _parse_saldo_line(text: str, label: str) -> Optional[Dict[str, Any]]:
    m = re.search(
        rf"{re.escape(label)}\s+"
        r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})\s+(\d+)",
        text,
    )
    if not m:
        return None
    return {
        "od": m.group(1),
        "do": m.group(2),
        "kwh": int(m.group(3)),
    }


def _parse_dane_energii_energa(text: str) -> Dict[str, Any]:
    """Dane odczytowe i energia pobrana / wprowadzona (prosument) z FV ENERGA."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    ppe_m = re.search(r"Kod PPE:\s*(\d+)", text)
    adres_m = re.search(r"Adres PPE:\s*(.+?)\s+Moc umowna:\s*([\d,]+)\s*kW", text, re.I)
    zab_m = re.search(r"Zabezpieczenie przedlicznikowe:\s*([^\n]+)", text, re.I)
    kwh12_m = re.search(
        r"zużytej energii elektrycznej w okresie ostatnich 12 miesięcy:\s*([\d\s]+)\s*kWh",
        text,
        re.I,
    )

    ln_pob = _line_after_marker(lines, "Pobranie energii", lambda s: s.upper().startswith("G"))
    ln_wpr = _line_after_marker(lines, "Wprowadzenie energii", lambda s: s.upper().startswith("G"))
    pobranie = _parse_meter_line(ln_pob) if ln_pob else None
    wprowadzenie = _parse_meter_line(ln_wpr) if ln_wpr else None
    if pobranie is None:
        pobranie = _find_meter_after_markers(
            text,
            ("Pobranie energii", "Pobrana energia", "pobranie energii czynnej", "DANE ODCZYTOWE"),
        )
    if wprowadzenie is None:
        wprowadzenie = _find_meter_after_markers(
            text,
            ("Wprowadzenie energii", "Wprowadzona energia", "oddanie energii", "wprowadzenie energii"),
        )
    saldo_dod = _parse_saldo_line(text, "Suma godzinowych sald dodatnich")
    saldo_ujem = _parse_saldo_line(text, "Suma godzinowych sald ujemnych")

    wprz_m = re.search(
        r"Suma godzinowych sald ujemnych\s+"
        r"\d{2}\.\d{2}\.\d{4}\s+\d{2}\.\d{2}\.\d{4}\s+\d+\s+kWh\s+"
        r"[\d,]+\s+[\d,]+\s+[\d,]+\s+([\d,]+)",
        text,
        re.I,
    )
    depozyt_stan_m = re.search(
        r"Stan depozytu\s+\d{2}\.\d{2}\.\d{4}\s+([\d\s,]+)\s*zł", text, re.I
    )
    depozyt_razem_m = re.search(r"Razem depozyt\s+([\d\s,]+)\s*zł", text, re.I)

    wiersze: List[Dict[str, Any]] = []
    if pobranie:
        wiersze.append({"typ": "pobranie", "opis": "Energia czynna (pobranie z sieci)", **pobranie})
    if saldo_dod:
        wiersze.append(
            {
                "typ": "saldo_dodatnie",
                "opis": "Suma godzinowych sald dodatnich",
                "ilosc_kwh": saldo_dod.get("kwh"),
                **saldo_dod,
            }
        )
    if wprowadzenie:
        wiersze.append({"typ": "wprowadzenie", "opis": "Energia czynna oddanie (do sieci)", **wprowadzenie})
    if saldo_ujem:
        wiersze.append(
            {
                "typ": "saldo_ujemne",
                "opis": "Suma godzinowych sald ujemnych",
                "ilosc_kwh": saldo_ujem.get("kwh"),
                **saldo_ujem,
            }
        )

    return {
        "punkt_poboru": {
            "kod_ppe": ppe_m.group(1) if ppe_m else "",
            "adres": adres_m.group(1).strip() if adres_m else "",
            "moc_umowna_kw": _pl_num(adres_m.group(2)) if adres_m else None,
            "zabezpieczenie": zab_m.group(1).strip() if zab_m else "",
            "zuzyto_12m_kwh": int(kwh12_m.group(1).replace(" ", "")) if kwh12_m else None,
            "prosument": "PROSUMENT" in text.upper(),
        },
        "pobranie": pobranie,
        "wprowadzenie": wprowadzenie,
        "saldo_dodatnie": saldo_dod,
        "saldo_ujemne": saldo_ujem,
        "wprowadzenie_rozliczenie_netto_zl": (
            _pl_num(wprz_m.group(1))
            if wprz_m
            else (_pl_num(depozyt_stan_m.group(1)) if depozyt_stan_m else None)
        ),
        "depozyt_stan_zl": _pl_num(depozyt_stan_m.group(1)) if depozyt_stan_m else None,
        "depozyt_razem_zl": _pl_num(depozyt_razem_m.group(1)) if depozyt_razem_m else None,
        "wiersze": wiersze,
    }


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

    dane_energii = _parse_dane_energii_energa(text)

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
        "dane_energii": dane_energii,
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
