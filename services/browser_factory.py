from __future__ import annotations

import base64
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from playwright.sync_api import sync_playwright

from ..core.db import SessionLocal
from ..core.models import Account
from ..utils.proxy import parse_proxy
from ..utils.text_fix import WORDSTAT_FETCH_NORMALIZER_SCRIPT
from .proxy_manager import Proxy, ProxyManager

BASE_DIR = Path("C:/AI/yandex")


@dataclass
class BrowserContextHandle:
    kind: str
    browser: Any
    context: Any
    page: Any
    proxy_id: Optional[str] = None
    release_cb: Callable[[], None] = lambda: None
    metadata: Dict[str, Any] = field(default_factory=dict)


def _resolve_account(account_id: int) -> Account:
    with SessionLocal() as session:
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f"Account {account_id} not found")
        return account


def _normalize_profile_path(raw_path: Optional[str], account_name: str) -> Path:
    if raw_path:
        path = Path(str(raw_path).strip())
    else:
        path = Path(".profiles") / account_name
    if path.is_absolute():
        return path
    return BASE_DIR / path


def _prepare_proxy(
    account: Account,
    manager: ProxyManager,
    *,
    geo: Optional[str] = None,
) -> tuple[Optional[Proxy], Optional[Dict[str, str]]]:
    proxy_obj = None
    if account.proxy_id:
        proxy_obj = manager.acquire(account.proxy_id, geo=geo)
    if proxy_obj:
        return proxy_obj, proxy_obj.playwright_config()

    parsed = parse_proxy(account.proxy) if account.proxy else None
    return None, parsed


def for_account(
    account_id: int,
    *,
    headless: bool = False,
    use_cdp: bool = False,
    chrome_path: Optional[str] = None,
    cdp_port: int = 9222,
    args: Optional[list[str]] = None,
    geo: Optional[str] = None,
    profile_override: Optional[str] = None,
) -> BrowserContextHandle:
    _clear_system_proxy_env()

    account = _resolve_account(account_id)
    profile_dir = _normalize_profile_path(profile_override or account.profile_path, account.name)
    profile_dir.parent.mkdir(parents=True, exist_ok=True)

    manager = ProxyManager.instance()
    proxy_obj, proxy_kwargs = _prepare_proxy(account, manager, geo=geo)

    chrome_exe = chrome_path or r"C:\Program Files\Google\Chrome\Application\chrome.exe"

    additional_args = list(args or [])
    proxy_requires_auth = False
    if proxy_obj and proxy_obj.has_auth:
        proxy_requires_auth = True
    elif proxy_kwargs and proxy_kwargs.get("username"):
        proxy_requires_auth = True

    proxy_server_for_resolver: Optional[str] = None
    if proxy_obj and proxy_obj.type.lower().startswith("socks"):
        proxy_server_for_resolver = proxy_obj.server.split("://")[-1]
    elif not proxy_obj and proxy_kwargs and proxy_kwargs.get("server", "").startswith("socks"):
        proxy_server_for_resolver = proxy_kwargs["server"].split("://")[-1]
    if proxy_server_for_resolver:
        proxy_host_only = proxy_server_for_resolver.split(":")[0]
        additional_args.append(f"--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE {proxy_host_only}")

    preflight = _preflight_proxy(proxy_obj, proxy_kwargs)
    if not preflight["ok"]:
        manager.release(proxy_obj)
        raise RuntimeError(f"Proxy preflight failed: {preflight['error']}")

    if use_cdp and proxy_requires_auth:
        use_cdp = False

    if not use_cdp:
        playwright = sync_playwright().start()
        launch_kwargs: Dict[str, Any] = {
            "user_data_dir": str(profile_dir),
            "headless": headless,
            "proxy": proxy_kwargs,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-infobars",
                *additional_args,
            ],
            "ignore_default_args": ["--enable-automation"],
        }
        chrome_path_obj = Path(chrome_exe)
        if chrome_path_obj.exists():
            launch_kwargs["executable_path"] = str(chrome_path_obj)
        else:
            launch_kwargs["channel"] = "chrome"
        try:
            browser = playwright.chromium.launch_persistent_context(**launch_kwargs)
        except Exception:
            playwright.stop()
            manager.release(proxy_obj)
            raise
        browser.add_init_script(script=WORDSTAT_FETCH_NORMALIZER_SCRIPT)
        for existing_page in browser.pages:
            existing_page.add_init_script(script=WORDSTAT_FETCH_NORMALIZER_SCRIPT)
            try:
                existing_page.evaluate(WORDSTAT_FETCH_NORMALIZER_SCRIPT)
            except Exception:
                pass
        page = browser.pages[0] if browser.pages else browser.new_page()
        _wire_logging(page)
        try:
            page.evaluate(WORDSTAT_FETCH_NORMALIZER_SCRIPT)
        except Exception:
            pass

        print(
            f"[BF] PW persistent (proxy={'none' if not proxy_obj else proxy_obj.id}) "
            f"preflight_ip={preflight.get('ip')}"
        )

        def _release() -> None:
            try:
                browser.close()
            finally:
                try:
                    playwright.stop()
                finally:
                    manager.release(proxy_obj)

        return BrowserContextHandle(
            kind="playwright",
            browser=browser,
            context=browser,
            page=page,
            proxy_id=proxy_obj.id if proxy_obj else None,
            release_cb=_release,
            metadata={
                "profile_dir": str(profile_dir),
                "preflight": preflight,
            },
        )

    cmd = [
        chrome_exe,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={profile_dir}",
        "--disable-extensions",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--start-maximized",
        *additional_args,
    ]

    if proxy_obj:
        cmd.append(proxy_obj.chrome_flag())
    elif proxy_kwargs:
        cmd.append(f'--proxy-server="{proxy_kwargs["server"]}"')

    process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    playwright = sync_playwright().start()
    browser = None
    deadline = time.time() + 10.0
    last_error: Optional[Exception] = None
    while time.time() < deadline:
        try:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            break
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
    if browser is None:
        process.terminate()
        playwright.stop()
        manager.release(proxy_obj)
        raise RuntimeError(f"Unable to connect to Chrome on port {cdp_port}: {last_error}")

        context = browser.contexts[0] if browser.contexts else browser.new_context()
        context.add_init_script(script=WORDSTAT_FETCH_NORMALIZER_SCRIPT)
        for existing_page in context.pages:
            existing_page.add_init_script(script=WORDSTAT_FETCH_NORMALIZER_SCRIPT)
            try:
                existing_page.evaluate(WORDSTAT_FETCH_NORMALIZER_SCRIPT)
            except Exception:
                pass
        page = context.pages[0] if context.pages else context.new_page()
        _wire_logging(page)
        try:
            page.evaluate(WORDSTAT_FETCH_NORMALIZER_SCRIPT)
        except Exception:
            pass
    print(
        f"[BF] CDP attach (proxy={'none' if not proxy_obj else proxy_obj.id}) "
        f"preflight_ip={preflight.get('ip')}"
    )

    def _release() -> None:
        try:
            browser.close()
        finally:
            try:
                playwright.stop()
            finally:
                try:
                    process.terminate()
                finally:
                    manager.release(proxy_obj)

    return BrowserContextHandle(
        kind="cdp",
        browser=browser,
        context=context,
        page=page,
        proxy_id=proxy_obj.id if proxy_obj else None,
        release_cb=_release,
        metadata={
            "profile_dir": str(profile_dir),
            "cdp_port": cdp_port,
            "preflight": preflight,
        },
    )


def start_for_account(
    account_id: int,
    *,
    headless: bool = False,
    use_cdp: bool = False,
    cdp_port: int = 9222,
    args: Optional[list[str]] = None,
    geo: Optional[str] = None,
    profile_override: Optional[str] = None,
) -> BrowserContextHandle:
    """Convenience alias that mirrors the signature from older code paths."""
    return for_account(
        account_id,
        headless=headless,
        use_cdp=use_cdp,
        cdp_port=cdp_port,
        args=args,
        geo=geo,
        profile_override=profile_override,
    )


__all__ = ["BrowserContextHandle", "for_account", "start_for_account"]


def _clear_system_proxy_env() -> None:
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        if key in os.environ:
            os.environ.pop(key, None)


def _preflight_proxy(
    proxy_obj: Optional[Proxy],
    proxy_kwargs: Optional[Dict[str, str]],
) -> Dict[str, Optional[str]]:
    if not proxy_obj and not proxy_kwargs:
        return {"ok": True, "ip": None, "error": None}

    scheme = None
    server = None
    username = None
    password = None
    if proxy_obj:
        server = proxy_obj.server
        scheme = proxy_obj.type
        username = proxy_obj.username
        password = proxy_obj.password
    elif proxy_kwargs:
        server = proxy_kwargs.get("server")
        username = proxy_kwargs.get("username")
        password = proxy_kwargs.get("password")
        if server:
            scheme = server.split("://")[0]

    if not server:
        return {"ok": False, "ip": None, "error": "Proxy server not specified"}

    if scheme and scheme.lower().startswith("socks"):
        # urllib не умеет socks, пропускаем проверку — Playwright подключит сам
        return {"ok": True, "ip": None, "error": None}

    if "://" not in server:
        server = f"{scheme or 'http'}://{server}"

    proxies = {"http": server, "https": server}
    handler = urllib.request.ProxyHandler(proxies)
    opener = urllib.request.build_opener(handler)
    if username:
        creds = f"{username}:{password or ''}".encode("utf-8")
        opener.addheaders = [("Proxy-Authorization", f"Basic {base64.b64encode(creds).decode('ascii')}")]

    try:
        with opener.open("https://api.ipify.org", timeout=10) as response:
            ip = response.read().decode("utf-8").strip()
            return {"ok": True, "ip": ip, "error": None}
    except Exception as exc:
        return {"ok": False, "ip": None, "error": str(exc)}


def _wire_logging(page: Any) -> None:
    try:
        page.on("requestfailed", lambda r: print(f"[BF][NET] FAIL {r.url} {r.failure}"))
        page.on("console", lambda m: print(f"[BF][CONSOLE] {m.type}: {m.text}"))
    except Exception:
        pass
