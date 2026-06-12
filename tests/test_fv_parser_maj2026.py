"""Test parsera FV — prosument z depozytem (maj 2026)."""
from pathlib import Path

from app.fv_parser import parse_energa_pdf_bytes
from app.fv_store import compute_split

PDF = Path(r"C:\Users\Dyba\Downloads\maj_0157092628_FES_00044.pdf")
SAMPLE = """
Rozliczenie za okres 01.05.2026 - 31.05.2026
wartość energii pobranej 262,64 zł
Pobrano z DEPOZYTU 120,63 zł
Wartość do zapłaty
142,01 zł
Kwota płatności: 142,01
1. ROZLICZENIE SPRZEDAŻY ENERGII POBRANEJ
Opłata handlowa 01.05.2026 31.05.2026 1,00 MC 16,1800 16,18 23
2. ROZLICZENIE DYSTRYBUCJI ENERGII ELEKTRYCZNEJ
Opłata abonamentowa 01.05.2026 31.05.2026 1,00 MC 0,7400 0,74 23
Razem wartość netto (1 + 2) 213,53
Suma godzinowych sald dodatnich 30.04.2026 31.05.2026 160
Rozliczenie energii elektrycznej i świadczenia usługi dystrybucji 213,53 49,11 262,64
"""


def test_maj2026_text_podsumowanie():
    from app.fv_parser import parse_energa_pdf_text

    p = parse_energa_pdf_text(SAMPLE)
    pod = p["podsumowanie"]
    assert pod["razem_brutto"] == 262.64
    assert pod["razem_netto"] == 213.53
    assert pod["depozyt_brutto"] == 120.63
    assert pod["do_zaplaty_brutto"] == 142.01


def test_maj2026_split_do_zaplaty():
    from app.fv_parser import parse_energa_pdf_text

    p = parse_energa_pdf_text(SAMPLE)
    meters = [
        {"meter_id": "7", "kwh": 50, "label": "Tomek"},
        {"meter_id": "8", "kwh": 50, "label": "Lonia"},
        {"meter_id": "9", "kwh": 50, "label": "Henia"},
    ]
    sp = compute_split(p, meters, {})
    assert sp["do_zaplaty_total"] == 142.01
    assert round(sum(m["do_zaplaty_brutto"] for m in sp["meters"]), 2) == 142.01
    assert round(sum(m["razem_brutto"] for m in sp["meters"]), 2) == 262.64


def test_maj2026_pdf_if_present():
    if not PDF.is_file():
        return
    p = parse_energa_pdf_bytes(PDF.read_bytes())
    pod = p["podsumowanie"]
    assert pod["do_zaplaty_brutto"] == 142.01
    assert pod["razem_brutto"] == 262.64
