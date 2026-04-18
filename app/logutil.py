"""
Logowanie do konsoli i do pliku logs/app.log (w katalogu projektu).
Format czasu: dd.mm.yy HH:MM:SS (konsola + plik). Żądania HTTP (uvicorn) też trafiają do pliku.
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

from sqlalchemy import text

_LOG = logging.getLogger("str_liczniki")

_DATE_FMT = "%d.%m.%y %H:%M:%S"
_LOG_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

_uvicorn_file_handlers_done = False


def mask_database_url(url: str) -> str:
    if not url or url.startswith("sqlite"):
        return url
    return re.sub(r"(://[^:/]+:)([^@]+)(@)", r"\1***\3", url, count=1)


def _same_file_handler(h: logging.Handler, log_file: Path) -> bool:
    if not isinstance(h, logging.FileHandler):
        return False
    try:
        return Path(h.baseFilename).resolve() == log_file.resolve()
    except Exception:
        return False


def _ensure_file_handler(logger: logging.Logger, log_file: Path, fmt: logging.Formatter) -> None:
    if any(_same_file_handler(h, log_file) for h in logger.handlers):
        return
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)


def _attach_uvicorn_to_file(log_file: Path, fmt: logging.Formatter) -> None:
    global _uvicorn_file_handlers_done
    if _uvicorn_file_handlers_done:
        return
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        _ensure_file_handler(lg, log_file, fmt)
    _uvicorn_file_handlers_done = True


def setup_logging(project_root: Path) -> None:
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "app.log"
    fmt = logging.Formatter(_LOG_FMT, datefmt=_DATE_FMT)

    if not _LOG.handlers:
        _LOG.setLevel(logging.INFO)
        _LOG.propagate = False

        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        _LOG.addHandler(fh)

        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        _LOG.addHandler(ch)

        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

        _LOG.info("Logi: konsola + plik %s (czas: dd.mm.yy HH:MM:SS)", log_file)

    _attach_uvicorn_to_file(log_file, fmt)


def log_database_startup() -> None:
    from .db import engine
    from .settings import get_settings

    s = get_settings()
    _LOG.info("DATABASE_URL (hasło ukryte): %s", mask_database_url(s.database_url))
    if s.database_url.startswith("sqlite"):
        _LOG.info("Tryb: SQLite (plik lokalny)")
    else:
        _LOG.info("Tryb: zdalna baza (URL jak wyżej)")

    try:
        with engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        _LOG.info("Połączenie z bazą: OK (test SELECT 1)")
    except Exception as e:
        _LOG.error("Połączenie z bazą: BŁĄD — %s", e, exc_info=True)
        msg = str(e)
        if "1049" in msg or "Unknown database" in msg:
            _LOG.error(
                "MySQL: nie ma takiej bazy w URL. Utwórz ją (np. CREATE DATABASE nazwa_bazy) "
                "albo ustaw w .env poprawny DATABASE_URL z istniejącą nazwą bazy."
            )
        if "1045" in msg or "Access denied" in msg:
            _LOG.error(
                "MySQL: odmowa dostępu — sprawdź użytkownika, hasło i uprawnienia hosta."
            )
        if "2003" in msg or "Can't connect" in msg:
            _LOG.error(
                "MySQL: brak połączenia z serwerem — sieć, firewall, bind-address na MySQL."
            )
