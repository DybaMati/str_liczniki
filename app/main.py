from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from . import str_data
from .logutil import log_database_startup, setup_logging
from .settings import get_settings

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

_LOG = logging.getLogger("str_liczniki")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(BASE_DIR)
    log_database_startup()
    yield


app = FastAPI(title="PV / liczniki dashboard", lifespan=lifespan)


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    _LOG.exception("Błąd SQL przy %s %s", request.method, request.url.path)
    orig = getattr(exc, "orig", None)
    detail = str(orig) if orig is not None else str(exc)
    return JSONResponse(
        status_code=503,
        content={"ok": False, "error": "błąd bazy danych", "detail": detail},
    )

METER_LABELS_DEFAULT = {
    "7": "Tomek L1",
    "8": "Lonia L2",
    "9": "Henia L3",
    "l1": "Tomek L1",
    "l2": "Lonia L2",
    "l3": "Henia L3",
    "tomek": "Tomek L1",
    "lonia": "Lonia L2",
    "henia": "Henia L3",
}


def _meter_labels() -> Dict[str, str]:
    raw = get_settings().meter_labels_json
    if not raw:
        return METER_LABELS_DEFAULT
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except json.JSONDecodeError:
        pass
    return METER_LABELS_DEFAULT


def _parse_date_ymd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _validate_date_range_not_inverted(date_from: str, date_to: str) -> None:
    if _parse_date_ymd(date_to) < _parse_date_ymd(date_from):
        raise HTTPException(
            status_code=400,
            detail="Data końcowa nie może być wcześniejsza niż początkowa.",
        )


def _fmt_ts(val: object) -> str:
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    s = str(val)
    if "T" in s and len(s) > 19:
        return s[:19].replace("T", " ")
    return s


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "title": "Start", "active": "home"},
    )


@app.get("/live", response_class=HTMLResponse)
async def page_live(request: Request):
    return templates.TemplateResponse(
        "live.html", {"request": request, "title": "Na żywo", "active": "live"}
    )


@app.get("/chart", response_class=HTMLResponse)
async def page_chart(request: Request):
    return templates.TemplateResponse(
        "chart.html", {"request": request, "title": "Wykres mocy", "active": "chart"}
    )


@app.get("/meters", response_class=HTMLResponse)
async def page_meters(request: Request):
    return templates.TemplateResponse(
        "meters.html",
        {
            "request": request,
            "title": "Zużycie liczników (kWh)",
            "active": "meters",
            "meter_labels": _meter_labels(),
        },
    )


@app.get("/api/live")
async def api_live():
    row = str_data.fetch_live()
    if not row:
        return JSONResponse({"ok": False, "error": "brak danych"})
    t = _fmt_ts(row.get("ts"))
    return {
        "ok": True,
        "time": t,
        "pv_ts": _fmt_ts(row.get("pv_ts")),
        "l1_ts": _fmt_ts(row.get("l1_ts")),
        "l2_ts": _fmt_ts(row.get("l2_ts")),
        "l3_ts": _fmt_ts(row.get("l3_ts")),
        "pv_w": float(row.get("pv_w") or 0),
        "l1_w": float(row.get("l1_w") or 0),
        "l2_w": float(row.get("l2_w") or 0),
        "l3_w": float(row.get("l3_w") or 0),
        "meter_cards": row.get("meter_cards") or [],
    }


@app.get("/api/history")
async def api_history(
    date_from: str = Query(..., alias="from"),
    date_to: str = Query(..., alias="to"),
):
    try:
        datetime.strptime(date_from, "%Y-%m-%d")
        datetime.strptime(date_to, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="from/to muszą być w formacie YYYY-MM-DD")
    _validate_date_range_not_inverted(date_from, date_to)
    out = str_data.fetch_history_merged(date_from, date_to)
    return {"ok": True, "data": out}


@app.get("/api/meters-delta")
async def api_meters_delta(
    date_from: str = Query(..., alias="from"),
    date_to: str = Query(..., alias="to"),
):
    try:
        datetime.strptime(date_from, "%Y-%m-%d")
        datetime.strptime(date_to, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="from/to muszą być w formacie YYYY-MM-DD")
    _validate_date_range_not_inverted(date_from, date_to)
    rows = str_data.fetch_meters_delta(date_from, date_to)
    labels = _meter_labels()
    items = []
    for r in rows:
        mid = str(r.get("meter_id", ""))
        items.append(
            {
                "meter_id": mid,
                "label": labels.get(mid, labels.get(mid.lower(), mid)),
                "start_kwh": r.get("start_kwh"),
                "start_ts": r.get("start_ts"),
                "end_kwh": r.get("end_kwh"),
                "end_ts": r.get("end_ts"),
                "kwh": r.get("kwh_delta"),
            }
        )
    return {"ok": True, "from": date_from, "to": date_to, "meters": items}
