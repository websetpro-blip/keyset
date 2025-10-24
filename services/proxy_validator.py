"""
Высокоуровневый валидатор прокси для UI и автоматических проверок.

Использует существующий модуль services.proxy_check (async).
"""

from __future__ import annotations

import asyncio
from typing import Dict, Optional

try:
    from ..utils.proxy import proxy_to_playwright
    from .proxy_check import test_proxy as _test_proxy
    from .proxy_manager import ProxyManager
except ImportError:
    from utils.proxy import proxy_to_playwright
    from .proxy_check import test_proxy as _test_proxy
    from .proxy_manager import ProxyManager


def _compose_proxy_url(raw: Optional[str]) -> Optional[str]:
    """
    Приводит строку прокси к формату http(s)://user:pass@host:port.
    Возвращает None, если строка не распознана.
    """
    if not raw:
        return None

    parsed = proxy_to_playwright(raw)
    if not parsed:
        return None

    server = parsed.get("server")
    if not server:
        return None

    scheme, _, host_port = server.partition("://")
    if not host_port:
        host_port = scheme
        scheme = "http"

    username = parsed.get("username")
    password = parsed.get("password", "")

    if username:
        return f"{scheme}://{username}:{password}@{host_port}"
    return f"{scheme}://{host_port}"


def validate_proxy(proxy_str: Optional[str], timeout: int = 10) -> Dict[str, object]:
    """
    Синхронная проверка прокси. Возвращает словарь:
        {
            "ok": bool,
            "ip": str | None,
            "latency_ms": int,
            "error": str | None,
        }
    """
    prepared = _compose_proxy_url(proxy_str)
    if not prepared:
        return {
            "ok": False,
            "ip": None,
            "latency_ms": 0,
            "error": "Некорректный формат прокси",
        }

    async def _run() -> Dict[str, object]:
        return await _test_proxy(prepared, timeout=timeout)

    try:
        return asyncio.run(_run())
    except RuntimeError:
        # already inside loop (например, PySide) — используем новый цикл
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()


def validate_proxy_by_id(proxy_id: str, timeout: int = 10) -> Dict[str, object]:
    """
    Проверяет прокси по идентификатору из ProxyManager.
    """
    manager = ProxyManager.instance()
    proxy = manager.get(proxy_id)
    if not proxy:
        return {
            "ok": False,
            "ip": None,
            "latency_ms": 0,
            "error": f"Прокси {proxy_id} не найден",
        }
    return validate_proxy(proxy.uri(include_credentials=True), timeout=timeout)


__all__ = ["validate_proxy", "validate_proxy_by_id"]
