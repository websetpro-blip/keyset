# -*- coding: utf-8 -*-
"""
Запуск отдельного пользовательского Chrome через Playwright.

Вместо запуска системного chrome.exe c параметрами командной строки
используем launch_persistent_context, который корректно прокидывает прокси
и не требует дополнительных расширений или CDP-хаков.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

try:  # Optional dependency
    from aiohttp_socks import ProxyConnector  # type: ignore
except Exception:  # pragma: no cover - dependency may be absent
    ProxyConnector = None

try:
    import aiohttp
    from aiohttp import BasicAuth
except Exception:  # pragma: no cover - dependency may be absent
    aiohttp = None  # type: ignore

from playwright.async_api import async_playwright

LOGGER = logging.getLogger(__name__)


@dataclass
class _RunningContext:
    thread: threading.Thread
    stop_event: threading.Event
    started_event: threading.Event
    error: Optional[str]
    proxy_config: Optional[Dict[str, str]]


class ChromeLauncherDirectParser:
    """
    Управляет пользовательскими экземплярами Chrome, поднятыми через Playwright.

    Один аккаунт ↔ один persistent context. Контекст живёт в отдельном потоке
    до тех пор, пока не будет вызван close().
    """

    CHROME_CHANNEL = "chrome"

    _running: Dict[str, _RunningContext] = {}
    _lock = threading.RLock()

    # ------------------------------------------------------------------ public
    @classmethod
    def launch(
        cls,
        account_name: str,
        profile_path: str,
        *,
        proxy_server: Optional[str] = None,
        proxy_username: Optional[str] = None,
        proxy_password: Optional[str] = None,
        start_url: str = "about:blank",
    ) -> threading.Thread:
        """
        Запустить Chrome в отдельном окне.

        Возвращает поток, в котором исполняется Playwright (для совместимости).
        """
        profile = cls._resolve_profile(profile_path)
        proxy = cls._build_proxy_config(account_name, proxy_server, proxy_username, proxy_password)

        cls.close(account_name)

        stop_event = threading.Event()
        started_event = threading.Event()

        thread = threading.Thread(
            target=cls._run_playwright,
            name=f"directparser-{account_name}",
            args=(account_name, profile, proxy, start_url, stop_event, started_event),
            daemon=True,
        )

        with cls._lock:
            cls._running[account_name] = _RunningContext(
                thread=thread,
                stop_event=stop_event,
                started_event=started_event,
                error=None,
                proxy_config=proxy,
            )

        thread.start()
        LOGGER.info("[%s] Playwright launcher thread started", account_name)

        if not started_event.wait(timeout=20):
            cls.close(account_name)
            raise RuntimeError("Playwright не смог запустить Chrome за 20 секунд")

        with cls._lock:
            ctx = cls._running.get(account_name)
            if ctx and ctx.error:
                message = ctx.error
                cls.close(account_name)
                raise RuntimeError(message)

        return thread

    @classmethod
    def close(cls, account_name: str) -> None:
        """Остановить контекст для указанного аккаунта."""
        with cls._lock:
            ctx = cls._running.pop(account_name, None)

        if ctx is None:
            return

        ctx.stop_event.set()
        ctx.thread.join(timeout=10)
        LOGGER.info("[%s] Playwright launcher thread stopped", account_name)

    @classmethod
    def close_all(cls) -> None:
        """Остановить все активные контексты."""
        with cls._lock:
            names = list(cls._running.keys())
        for name in names:
            cls.close(name)

    # ---------------------------------------------------------------- helpers
    @classmethod
    def _run_playwright(
        cls,
        account_name: str,
        profile_dir: Path,
        proxy_config: Optional[Dict[str, str]],
        start_url: str,
        stop_event: threading.Event,
        started_event: threading.Event,
    ) -> None:
        async def runner() -> None:
            await cls._launch_async(
                account_name,
                profile_dir,
                proxy_config,
                start_url,
                stop_event,
                started_event,
            )

        try:
            asyncio.run(runner())
        except Exception:  # pragma: no cover - поток завершается, исключение уже залогировано
            LOGGER.exception("[%s] Playwright runner crashed", account_name)
            with cls._lock:
                ctx = cls._running.get(account_name)
                if ctx:
                    ctx.error = "Не удалось запустить Chrome через Playwright (см. логи)"
            started_event.set()

    @classmethod
    async def _launch_async(
        cls,
        account_name: str,
        profile_dir: Path,
        proxy_config: Optional[Dict[str, str]],
        start_url: str,
        stop_event: threading.Event,
        started_event: threading.Event,
    ) -> None:
        profile_dir.mkdir(parents=True, exist_ok=True)

        LOGGER.info("[%s] Launching Chrome via Playwright (profile=%s)", account_name, profile_dir)

        try:
            async with async_playwright() as playwright:
                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    channel=cls.CHROME_CHANNEL,
                    headless=False,
                    proxy=proxy_config,
                    bypass_csp=True,
                    ignore_https_errors=True,
                    locale="ru-RU",
                    viewport=None,
                    args=[
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                )

                LOGGER.info("[%s] Chrome persistent context ready", account_name)
                started_event.set()

                if start_url and start_url != "about:blank":
                    page = await context.new_page()
                    try:
                        await page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
                        LOGGER.info("[%s] Start URL loaded: %s", account_name, start_url)
                    except Exception:
                        LOGGER.exception("[%s] Failed to open start URL: %s", account_name, start_url)

                # Основной цикл: ждём остановки
                while not stop_event.is_set():
                    await asyncio.sleep(0.5)

                await context.close()
                LOGGER.info("[%s] Chrome context closed", account_name)
        except Exception as exc:
            LOGGER.exception("[%s] Unable to launch Chrome via Playwright", account_name)
            with cls._lock:
                ctx = cls._running.get(account_name)
                if ctx:
                    ctx.error = f"Playwright: {type(exc).__name__}: {exc}"
            started_event.set()
        finally:
            with cls._lock:
                ctx = cls._running.get(account_name)
                if ctx and ctx.thread is threading.current_thread():
                    cls._running.pop(account_name, None)

    # ---------------------------------------------------------------- parsing helpers
    @staticmethod
    def _resolve_profile(profile_path: str) -> Path:
        path = Path(profile_path)
        if not path.is_absolute():
            path = Path("C:/AI/yandex") / path
        return path

    @classmethod
    def _build_proxy_config(
        cls,
        account_name: str,
        proxy_server: Optional[str],
        proxy_username: Optional[str],
        proxy_password: Optional[str],
    ) -> Optional[Dict[str, str]]:
        if not proxy_server:
            return None

        data = cls._parse_proxy(
            proxy_server,
            proxy_username,
            proxy_password,
            account_name=account_name,
        )
        server = data["server"]

        config: Dict[str, str] = {"server": server}
        if data.get("username"):
            config["username"] = data["username"]
        if data.get("password"):
            config["password"] = data["password"]

        LOGGER.info(
            "[%s] Proxy config built: %s (auth=%s)",
            account_name,
            server,
            "yes" if config.get("username") else "no",
        )
        return config

    @staticmethod
    def _parse_proxy(
        proxy_server: str,
        proxy_username: Optional[str] = None,
        proxy_password: Optional[str] = None,
        *,
        account_name: str = "unknown",
    ) -> Dict[str, str]:
        """
        Нормализовать строку прокси и вернуть dict для Playwright.

        Принимает host:port или строку со схемой.
        Username/password по умолчанию берутся из аргументов, но если в строке
        была auth-часть user:pass@host:port — она будет использована.
        """
        raw = proxy_server.strip()
        if not raw:
            raise ValueError("Proxy server string is empty")

        # Если в строке уже есть схема, используем её, иначе считаем http
        parsed = urlparse(raw if "://" in raw else f"http://{raw}")
        if not parsed.hostname or not parsed.port:
            raise ValueError(f"Invalid proxy format: {proxy_server}")

        username = proxy_username or parsed.username or ""
        password = proxy_password or parsed.password or ""
        scheme = parsed.scheme or "http"

        host_port = f"{parsed.hostname}:{parsed.port}"
        server = f"{scheme}://{host_port}"

        return {
            "account": account_name,
            "server": server,
            "scheme": scheme,
            "host": parsed.hostname,
            "port": parsed.port,
            "username": username,
            "password": password,
        }

    # ------------------------------------------------------------------ HTTP helpers
    @classmethod
    async def get_http_session(cls, account_name: str):
        """
        Вернуть aiohttp.ClientSession с тем же прокси, что и у браузера.

        Используйте это для REST-запросов (Wordstat API и т.п.) чтобы гарантировать,
        что запросы идут через тот же прокси-канал.
        """
        if aiohttp is None:
            raise RuntimeError("aiohttp не установлен: pip install aiohttp")

        with cls._lock:
            ctx = cls._running.get(account_name)

        if ctx is None or not ctx.proxy_config:
            LOGGER.error("[%s] Proxy config not available for HTTP session", account_name)
            return None

        proxy_url = ctx.proxy_config["server"]
        username = ctx.proxy_config.get("username", "")
        password = ctx.proxy_config.get("password", "")

        connector = None
        if ProxyConnector is not None:
            try:
                connector = ProxyConnector.from_url(proxy_url)
            except Exception:
                LOGGER.debug("[%s] Failed to init ProxyConnector", account_name, exc_info=True)
                connector = None

        if connector is None:
            connector = aiohttp.TCPConnector(ssl=False)

        session = aiohttp.ClientSession(connector=connector, trust_env=False)

        if ProxyConnector is None or not isinstance(connector, ProxyConnector):
            session._default_proxy = proxy_url  # type: ignore[attr-defined]
            if username:
                session._default_proxy_auth = BasicAuth(username, password)  # type: ignore[attr-defined]

        LOGGER.info("[%s] HTTP session created via proxy %s", account_name, proxy_url)
        return session


__all__ = ["ChromeLauncherDirectParser"]
