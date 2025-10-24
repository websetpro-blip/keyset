from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional, List

from playwright.sync_api import sync_playwright

try:
    from ..core.db import SessionLocal
    from ..core.models import Account
    from ..utils.proxy import proxy_to_playwright
    from ..utils.text_fix import WORDSTAT_FETCH_NORMALIZER_SCRIPT
    from .proxy_manager import Proxy, ProxyManager
    from .chrome_launcher import ChromeLauncher
except ImportError:
    from core.db import SessionLocal
    from core.models import Account
    from utils.proxy import proxy_to_playwright
    from utils.text_fix import WORDSTAT_FETCH_NORMALIZER_SCRIPT
    from .proxy_manager import Proxy, ProxyManager
    from .chrome_launcher import ChromeLauncher

BASE_DIR = ChromeLauncher.BASE_DIR
RUNTIME_DIR = BASE_DIR / "runtime"
PROXY_EXT_DIR = RUNTIME_DIR / "proxy_extensions"
BROWSER_SETTINGS_PATH = BASE_DIR / "config" / "browser_settings.json"
_BROWSER_SETTINGS_CACHE: Optional[Dict[str, Any]] = None


@dataclass
class BrowserContextHandle:
    kind: str
    browser: Any
    context: Any
    page: Any
    proxy_id: Optional[str] = None
    release_cb: Callable[[], None] = lambda: None
    metadata: Dict[str, Any] = field(default_factory=dict)


def _load_browser_settings() -> Dict[str, Any]:
    global _BROWSER_SETTINGS_CACHE
    if _BROWSER_SETTINGS_CACHE is None:
        try:
            raw = BROWSER_SETTINGS_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            _BROWSER_SETTINGS_CACHE = {}
        else:
            try:
                _BROWSER_SETTINGS_CACHE = json.loads(raw)
            except json.JSONDecodeError:
                _BROWSER_SETTINGS_CACHE = {}
    return _BROWSER_SETTINGS_CACHE or {}


def _browser_config_accounts() -> list[Dict[str, Any]]:
    settings = _load_browser_settings()
    accounts = settings.get("accounts")
    return accounts if isinstance(accounts, list) else []


def _browser_config_args() -> list[str]:
    settings = _load_browser_settings()
    args = settings.get("browser_args")
    if isinstance(args, list):
        return [str(item) for item in args if isinstance(item, str)]
    return []


def _config_entry_for_account(account_name: str) -> Optional[Dict[str, Any]]:
    for entry in _browser_config_accounts():
        if entry.get("name") == account_name:
            return entry
    return None

def _mask_proxy_uri(uri: Optional[str]) -> Optional[str]:
    if not uri:
        return uri
    working = uri
    scheme = ''
    if '://' in working:
        scheme, working = working.split('://', 1)
    if '@' not in working:
        return uri
    creds, host = working.split('@', 1)
    user = creds.split(':', 1)[0] if ':' in creds else creds
    prefix = f"{scheme}://" if scheme else ''
    return f"{prefix}{user}:***@{host}"


def _strip_proxy_credentials(uri: Optional[str]) -> Optional[str]:
    if not uri:
        return uri
    if '://' not in uri:
        return uri.split('@', 1)[-1]
    scheme, rest = uri.split('://', 1)
    host_part = rest.split('@', 1)[-1]
    return f"{scheme}://{host_part}"



def _iter_candidate_ports(preferred: Optional[int] = None, *, start: int = 9222, limit: int = 50):
    if preferred:
        yield preferred
    port = start
    attempts = 0
    while attempts < limit:
        if port != preferred:
            yield port
        port += 1
        attempts += 1


def _pick_available_port(preferred: Optional[int] = None) -> int:
    for candidate in _iter_candidate_ports(preferred):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", candidate))
            except OSError:
                continue
        return candidate
    raise RuntimeError("Unable to allocate free CDP port")


def _resolve_account(account_id: int) -> Account:
    with SessionLocal() as session:
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f"Account {account_id} not found")
        return account


def _normalize_profile_path(raw_path: Optional[str], account_name: str) -> Path:
    return ChromeLauncher._normalise_profile_path(raw_path, account_name)


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

    parsed = proxy_to_playwright(account.proxy)
    return None, parsed


def for_account(
    account_id: int,
    *,
    headless: bool = False,
    use_cdp: bool = False,
    chrome_path: Optional[str] = None,
    cdp_port: Optional[int] = None,
    args: Optional[list[str]] = None,
    geo: Optional[str] = None,
    profile_override: Optional[str] = None,
    target_url: Optional[str] = None,
) -> BrowserContextHandle:
    _clear_system_proxy_env()

    account = _resolve_account(account_id)
    profile_dir = _normalize_profile_path(profile_override or account.profile_path, account.name)
    profile_dir.parent.mkdir(parents=True, exist_ok=True)

    manager = ProxyManager.instance()
    proxy_obj, proxy_kwargs = _prepare_proxy(account, manager, geo=geo)
    if proxy_obj:
        print(f"[BF] Proxy manager entry for {account.name}: {proxy_obj.display_label()} (auth={'yes' if proxy_obj.has_auth else 'no'})")
    elif proxy_kwargs:
        label = proxy_kwargs.get('server', '')
        if proxy_kwargs.get('username'):
            label = f"{label} (login={proxy_kwargs['username']})"
        print(f"[BF] Proxy config entry for {account.name}: {label}")
    else:
        print(f"[BF] Proxy disabled for {account.name}")

    resolved_proxy_uri: Optional[str] = None

    config_entry = _config_entry_for_account(account.name)
    if not proxy_obj and not proxy_kwargs and config_entry:
        config_proxy = config_entry.get("proxy")
        if isinstance(config_proxy, str) and config_proxy.strip():
            parsed_proxy = proxy_to_playwright(config_proxy.strip())
            if parsed_proxy:
                proxy_kwargs = parsed_proxy

    chrome_exe = chrome_path or r"C:\Program Files\Google\Chrome\Application\chrome.exe"

    additional_args = list(args or [])
    for extra_arg in _browser_config_args():
        if extra_arg not in additional_args:
            additional_args.append(extra_arg)

    proxy_requires_auth = False
    if proxy_obj and proxy_obj.has_auth:
        proxy_requires_auth = True
        resolved_proxy_uri = proxy_obj.uri(include_credentials=True)
    elif proxy_kwargs and proxy_kwargs.get("username"):
        proxy_requires_auth = True
    if resolved_proxy_uri is None and proxy_kwargs:
        server = proxy_kwargs.get("server", "")
        scheme, _, host_port = server.partition("://")
        if not host_port:
            host_port = scheme
            scheme = "http"
        username = proxy_kwargs.get("username")
        password = proxy_kwargs.get("password", "")
        if username:
            resolved_proxy_uri = f"{scheme}://{username}:{password}@{host_port}"
        elif server:
            resolved_proxy_uri = f"{scheme}://{host_port}"

    if resolved_proxy_uri:
        print(f"[BF] Proxy URI for {account.name}: {_mask_proxy_uri(resolved_proxy_uri)}")

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

    proxy_extension_dir: Optional[Path] = None
    if use_cdp and proxy_requires_auth:
        try:
            proxy_extension_dir = _ensure_proxy_extension(proxy_obj, proxy_kwargs)
        except Exception as exc:
            print(f"[BF] Proxy extension error: {exc}")
            proxy_extension_dir = None
        if proxy_extension_dir is None:
            use_cdp = False

    if not use_cdp:
        playwright = sync_playwright().start()
        launch_kwargs: Dict[str, Any] = {
            "user_data_dir": str(profile_dir),
            "headless": headless,
            "proxy": proxy_kwargs,
            "args": [
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
        if target_url:
            try:
                page.goto(target_url, wait_until="networkidle")
            except Exception:
                try:
                    page.goto(target_url)
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

    resolved_port = cdp_port
    if config_entry and resolved_port is None:
        cfg_port = config_entry.get("cdp_port")
        if isinstance(cfg_port, int):
            resolved_port = cfg_port
        elif isinstance(cfg_port, str) and cfg_port.isdigit():
            resolved_port = int(cfg_port)
    try:
        resolved_port = _pick_available_port(resolved_port)
    except RuntimeError:
        manager.release(proxy_obj)
        raise

    cmd = [
        chrome_exe,
        f"--remote-debugging-port={resolved_port}",
        f"--user-data-dir={profile_dir}",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
        *additional_args,
    ]

    if proxy_extension_dir:
        print(f"[BF] Proxy auth extension enabled: {proxy_extension_dir}")
        ext_path = str(proxy_extension_dir).replace("\\", "/")
        cmd.append(f'--disable-extensions-except="{ext_path}"')
        cmd.append(f'--load-extension="{ext_path}"')
    else:
        cmd.append("--disable-extensions")

    proxy_flag = None
    if resolved_proxy_uri:
        proxy_flag = _strip_proxy_credentials(resolved_proxy_uri)
    elif proxy_obj:
        scheme, _, host_port = proxy_obj.server.partition("://")
        proxy_flag = f"{scheme}://{host_port}"
    elif proxy_kwargs:
        server = proxy_kwargs.get("server")
        if server:
            proxy_flag = _strip_proxy_credentials(server)
    if proxy_flag:
        cmd.append(f'--proxy-server={proxy_flag}')
        print(f"[BF] Chrome proxy flag for {account.name}: {_mask_proxy_uri(proxy_flag)}")
    else:
        print(f"[BF] Chrome proxy flag for {account.name}: none")

    if target_url:
        cmd.append(target_url)

    safe_cmd: List[str] = []
    for arg in cmd:
        if arg.startswith('--proxy-server='):
            value = arg.split('=', 1)[1]
            safe_cmd.append(f"--proxy-server={_mask_proxy_uri(value)}")
        else:
            safe_cmd.append(arg)
    print(f"[BF] Launch Chrome command for {account.name}: {' '.join(safe_cmd)}")

    process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    playwright = sync_playwright().start()
    browser = None
    deadline = time.time() + 10.0
    last_error: Optional[Exception] = None
    while time.time() < deadline:
        try:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{resolved_port}")
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
    if target_url:
        try:
            navigated = False
            try:
                current_url = page.url
            except Exception:
                current_url = ""
            if not current_url or current_url in {"about:blank", "chrome://newtab/"}:
                page.goto(target_url, wait_until="networkidle")
                navigated = True
            if not navigated:
                new_page = context.new_page()
                new_page.goto(target_url, wait_until="networkidle")
        except Exception:
            try:
                page.goto(target_url)
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
                    if proxy_extension_dir and proxy_extension_dir.exists():
                        shutil.rmtree(proxy_extension_dir, ignore_errors=True)
                    manager.release(proxy_obj)

    metadata: Dict[str, Any] = {
        "profile_dir": str(profile_dir),
        "cdp_port": resolved_port,
        "preflight": preflight,
    }
    if resolved_proxy_uri:
        metadata["proxy_uri"] = resolved_proxy_uri
    if proxy_extension_dir:
        metadata["proxy_extension_dir"] = str(proxy_extension_dir)
    if target_url:
        metadata["target_url"] = target_url

    return BrowserContextHandle(
        kind="cdp",
        browser=browser,
        context=context,
        page=page,
        proxy_id=proxy_obj.id if proxy_obj else None,
        release_cb=_release,
        metadata=metadata,
    )


def start_for_account(
    account_id: int,
    *,
    headless: bool = False,
    use_cdp: bool = False,
    cdp_port: Optional[int] = None,
    args: Optional[list[str]] = None,
    geo: Optional[str] = None,
    profile_override: Optional[str] = None,
    target_url: Optional[str] = None,
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
        target_url=target_url,
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


def _ensure_proxy_extension(
    proxy: Optional[Proxy] = None,
    proxy_kwargs: Optional[Dict[str, str]] = None,
) -> Optional[Path]:
    username_value: Optional[str] = None
    password_value: Optional[str] = None
    server_value: Optional[str] = None
    proxy_id: str = "proxy"

    if proxy and proxy.has_auth:
        username_value = proxy.username or ""
        password_value = proxy.password or ""
        server_value = proxy.server
        proxy_id = proxy.id
    elif proxy_kwargs and proxy_kwargs.get("username"):
        username_value = proxy_kwargs.get("username") or ""
        password_value = proxy_kwargs.get("password") or ""
        server_value = proxy_kwargs.get("server")
        proxy_id = f"cfg_{int(time.time() * 1000)}"
    else:
        return None

    if not server_value:
        return None

    try:
        scheme, _, host_port = server_value.partition("://")
        if not host_port:
            host_port = scheme
            scheme = "http"
        host, _, port = host_port.partition(":")
        port = port or "80"
    except Exception:
        return None

    PROXY_EXT_DIR.mkdir(parents=True, exist_ok=True)
    ext_dir = PROXY_EXT_DIR / f"{proxy_id}_{int(time.time() * 1000)}"
    ext_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "manifest_version": 3,
        "name": f"ProxyAuth {proxy_id}",
        "version": "1.0",
        "permissions": [
            "webRequest",
            "webRequestAuthProvider",
            "webRequestBlocking",
        ],
        "host_permissions": ["<all_urls>"],
        "background": {"service_worker": "background.js"},
        "minimum_chrome_version": "109",
    }

    manifest_path = ext_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    username = json.dumps(username_value or "")
    password = json.dumps(password_value or "")

    background = f"""
chrome.webRequest.onAuthRequired.addListener(
  (details) => {{
    return {{
      authCredentials: {{
        username: {username},
        password: {password}
      }}
    }};
  }},
  {{ urls: ["<all_urls>"] }},
  ["asyncBlocking"]
);
"""
    (ext_dir / "background.js").write_text(background.strip() + "\n", encoding="utf-8")
    return ext_dir
