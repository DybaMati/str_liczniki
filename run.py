"""
Uruchomienie serwera www (domyślnie port z .env lub 8765).

Przykład:
  python run.py
  set PORT=9000 && python run.py
"""
from __future__ import annotations

import uvicorn

from app.settings import get_settings


def main() -> None:
    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, factory=False)


if __name__ == "__main__":
    main()
