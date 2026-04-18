from __future__ import annotations

import ipaddress
import logging
from typing import List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

_LOG = logging.getLogger("str_liczniki")


def parse_ip_rules(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def get_client_ip(request: Request, trust_x_forwarded_for: bool) -> str:
    if trust_x_forwarded_for:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            left = xff.split(",")[0].strip()
            if left:
                return left
    if request.client and request.client.host:
        return request.client.host
    return ""


def client_ip_matches(ip_str: str, rules: List[str]) -> bool:
    if not rules:
        return True
    ip_str = (ip_str or "").strip()
    if not ip_str:
        return False
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        _LOG.warning("Niepoprawny adres klienta: %r", ip_str)
        return False
    for rule in rules:
        try:
            if "/" in rule:
                net = ipaddress.ip_network(rule, strict=False)
                if addr in net:
                    return True
            else:
                if addr == ipaddress.ip_address(rule):
                    return True
        except ValueError:
            _LOG.warning("Niepoprawna regula IP (pominieto): %r", rule)
            continue
    return False


def register_ip_allowlist(app: FastAPI, templates: Jinja2Templates) -> None:
    """Jesli ALLOWED_CLIENT_IPS jest ustawione — tylko te adresy / sieci maja dostep."""

    @app.middleware("http")
    async def _ip_allowlist_middleware(request: Request, call_next):
        from .settings import get_settings

        s = get_settings()
        rules = parse_ip_rules(s.allowed_client_ips)
        if not rules:
            return await call_next(request)

        ip = get_client_ip(request, s.trust_x_forwarded_for)
        if client_ip_matches(ip, rules):
            return await call_next(request)

        _LOG.info("Odmowa dostepu IP=%s sciezka=%s", ip, request.url.path)

        if request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": "dostep niedozwolony"},
            )

        return templates.TemplateResponse(
            "denied.html",
            {
                "request": request,
                "title": s.denied_page_title,
                "denied_message": s.denied_page_message,
            },
            status_code=403,
        )
