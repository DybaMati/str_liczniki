"""
Uruchomienie serwera www (domyślnie port z .env lub 887).

Przykład:
  python run.py
  set PORT=9000 && python run.py
"""
from __future__ import annotations

import copy
from pathlib import Path

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from app.logutil import setup_logging
from app.settings import get_settings


def main() -> None:
    setup_logging(Path(__file__).resolve().parent)
    s = get_settings()
    log_config = copy.deepcopy(LOGGING_CONFIG)
    # Ujednolicenie konsoli uvicorn: INFO i access z data dd-mm-rr hh:mm:ss.
    log_config["formatters"]["default"]["fmt"] = "%(asctime)s [%(levelprefix)s] %(message)s"
    log_config["formatters"]["default"]["datefmt"] = "%d-%m-%y %H:%M:%S"
    log_config["formatters"]["access"]["fmt"] = (
        "%(asctime)s [%(levelprefix)s] %(client_addr)s - \"%(request_line)s\" %(status_code)s"
    )
    log_config["formatters"]["access"]["datefmt"] = "%d-%m-%y %H:%M:%S"
    uvicorn.run("app.main:app", host=s.host, port=s.port, factory=False, log_config=log_config)


if __name__ == "__main__":
    main()
