from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Mapping, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.sql.elements import TextClause

from .settings import get_settings


def get_engine() -> Engine:
    s = get_settings()
    connect_args: dict = {}
    if s.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(
        s.database_url,
        connect_args=connect_args,
        future=True,
        pool_pre_ping=True,
    )


_engine: Optional[Engine] = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def reset_engine() -> None:
    global _engine
    _engine = None


@contextmanager
def connect() -> Iterator[Connection]:
    with engine().connect() as conn:
        yield conn


def row_to_dict(row: Any) -> Dict[str, Any]:
    m = row._mapping
    return dict(m)


def fetch_one(sql: Any, params: Optional[Mapping[str, Any]] = None) -> Optional[Dict[str, Any]]:
    params = params or {}
    with connect() as conn:
        r = conn.execute(sql if isinstance(sql, TextClause) else text(str(sql)), params).mappings().first()
    return dict(r) if r else None


def fetch_all(sql: Any, params: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    params = params or {}
    with connect() as conn:
        rows = conn.execute(sql if isinstance(sql, TextClause) else text(str(sql)), params).mappings().all()
    return [dict(x) for x in rows]
