"""DirectParser-style Chrome launcher for KeySet."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

try:  # Optional dependency used if available
    from aiohttp_socks import ProxyConnector  # type: ignore
except Exception:  # pragma: no cover - fallback when package absent
    ProxyConnector = None

try:
    import aiohttp
    from aiohttp import BasicAuth
except Exception:  # pragma: no cover - runtime error will be raised on use
    aiohttp = None  # type: ignore

LOGGER = logging.getLogger(__name__)


class ChromeLauncherDirectParser:
    """Launch Chrome using the DirectParser proxy workflow."""

    CHROME_PATH = Path(r"C:/Program Files/Google/Chrome/Application/chrome.exe")
    BASE_DIR = Path(r"C:/AI/yandex-local")
    EXTENSIONS_ROOT = BASE_DIR / "runtime" / "proxy_extensions"

    _processes: Dict[str, subprocess.Popen] = {}
    _proxy_settings: Dict[str, dict] = {}

    @classmethod
    def launch(
        cls,
        account_name: str,
        profile_path: str,
        cdp_port: int,
        proxy_server: str,
        *,
        proxy_username: Optional[str] = None,
        proxy_password: Optional[str] = None,
        start_url: str = "about:blank",
    ) -> subprocess.Popen:
        """Launch Chrome and remember proxy settings for HTTP reuse."""

        proxy_data = cls._parse_proxy(proxy_server, proxy_username, proxy_password)
        LOGGER.info("[%s] Parsed proxy: %s", account_name, proxy_data)

        profile_dir = cls._resolve_profile(profile_path)
        profile_dir.mkdir(parents=True, exist_ok=True)

        # Persist proxy settings near the profile as DirectParser does (proxy.txt)
        cls._write_profile_proxy(profile_dir, proxy_data)

        args = [
            str(cls._resolve_chrome_executable()),
            f"--user-data-dir={profile_dir.as_posix()}",
            f"--remote-debugging-port={cdp_port}",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]

        proxy_scheme = "http" if proxy_data["is_http"] else "socks5"
        proxy_flag = f"{proxy_scheme}://{proxy_data['server']}:{proxy_data['port']}"
        args.append(f"--proxy-server={proxy_flag}")
        args.append(start_url)

        env = {}
        extension_dir: Optional[Path] = None
        if proxy_data.get("username") and proxy_data.get("password"):
            cls._cleanup_proxy_extensions()
            extension_dir = cls._create_proxy_extension(
                proxy_data["username"], proxy_data["password"]
            )
            ext_path = extension_dir.as_posix()
            args.extend([
                f"--load-extension={ext_path}",
                f"--disable-extensions-except={ext_path}",
            ])

        env_proxy = proxy_data["full_url"]
        env.update(
            {
                "HTTP_PROXY": env_proxy,
                "http_proxy": env_proxy,
                "HTTPS_PROXY": env_proxy,
                "https_proxy": env_proxy,
            }
        )

        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={**os.environ, **env},
            )
        except FileNotFoundError as exc:  # pragma: no cover - surfaced to caller
            raise
        except Exception as exc:  # pragma: no cover - surfaced to caller
            LOGGER.error("[%s] Unable to launch Chrome: %s", account_name, exc)
            raise

        cls._processes[account_name] = {"proc": proc, "extension": extension_dir}
        cls._proxy_settings[account_name] = proxy_data
        LOGGER.info("[%s] Chrome started PID=%s CDP=%s", account_name, proc.pid, cdp_port)
        return proc

    # ------------------------------------------------------------------ helpers
    @classmethod
    def _resolve_profile(cls, profile_path: str) -> Path:
        path = Path(profile_path)
        if not path.is_absolute():
            path = cls.BASE_DIR / profile_path
        return path

    @classmethod
    def _resolve_chrome_executable(cls) -> Path:
        if cls.CHROME_PATH.exists():
            return cls.CHROME_PATH
        raise FileNotFoundError(
            "Chrome executable not found. Update CHROME_PATH in ChromeLauncherDirectParser."
        )

    @classmethod
    def _parse_proxy(
        cls,
        server: str,
        username: Optional[str],
        password: Optional[str],
    ) -> dict:
        server = server.strip()
        if not server:
            raise ValueError("Proxy server is empty")

        scheme = "http"
        if "://" in server:
            parsed = urlparse(server if server.startswith("http") else f"http://{server}")
            host = parsed.hostname or ""
            port = parsed.port or 0
        else:
            parts = server.split(":", 1)
            host = parts[0]
            port = int(parts[1]) if len(parts) == 2 else 0

        if not host or not port:
            raise ValueError(f"Invalid proxy server: {server}")

        user = username or ""
        pwd = password or ""
        auth_part = f"{user}:{pwd}@" if user else ""
        full_url = f"{scheme}://{auth_part}{host}:{port}"

        return {
            "server": host,
            "port": port,
            "username": user,
            "password": pwd,
            "is_http": True,
            "full_url": full_url,
        }

    @classmethod
    def _write_profile_proxy(cls, profile_dir: Path, proxy_data: dict) -> None:
        try:
            proxy_file = profile_dir / "proxy.txt"
            payload = {
                "server": proxy_data["server"],
                "Port": proxy_data["port"],
                "IsHttp": proxy_data["is_http"],
                "name": proxy_data.get("username", ""),
                "password": proxy_data.get("password", ""),
            }
            proxy_file.write_text(json.dumps(payload), encoding="utf-8")
        except Exception as exc:  # pragma: no cover - non critical
            LOGGER.warning("Failed to write proxy.txt for %s: %s", profile_dir, exc)

    # ------------------------------------------------------------------ session helpers
    @classmethod
    async def get_http_session(cls, account_name: str):
        """Return aiohttp session configured with the same proxy."""
        if aiohttp is None:
            raise RuntimeError("aiohttp is required for HTTP session support")

        proxy_data = cls._proxy_settings.get(account_name)
        if not proxy_data:
            LOGGER.error("[%s] Proxy settings not available", account_name)
            return None

        proxy_url = proxy_data["full_url"]
        connector = None
        if ProxyConnector is not None:
            try:
                connector = ProxyConnector.from_url(proxy_url)
            except Exception as exc:  # pragma: no cover
                LOGGER.warning("[%s] Failed to init ProxyConnector: %s", account_name, exc)
                connector = None

        if connector is None:
            connector = aiohttp.TCPConnector(ssl=False)

        session = aiohttp.ClientSession(connector=connector, trust_env=False)
        # Set default proxy if connector does not handle it
        if not isinstance(connector, ProxyConnector):
            session._default_proxy = proxy_url  # type: ignore[attr-defined]
            if proxy_data.get("username"):
                session._default_proxy_auth = BasicAuth(  # type: ignore[attr-defined]
                    proxy_data["username"], proxy_data.get("password", "")
                )

        LOGGER.info("[%s] HTTP session ready via %s", account_name, proxy_url)
        return session

    # ------------------------------------------------------------------ lifecycle
    @classmethod
    def close(cls, account_name: str) -> None:
        data = cls._processes.pop(account_name, None)
        if data:
            proc = data.get("proc")
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                except Exception:  # pragma: no cover
                    proc.kill()
            ext_dir = data.get("extension")
            if ext_dir:
                try:
                    for _ in range(3):
                        if ext_dir.exists():
                            import shutil

                            shutil.rmtree(ext_dir, ignore_errors=True)
                        else:
                            break
                except Exception:  # pragma: no cover
                    LOGGER.debug("Failed to remove proxy extension", exc_info=True)
        cls._proxy_settings.pop(account_name, None)
        LOGGER.info("[%s] Browser closed", account_name)

    @classmethod
    def close_all(cls) -> None:
        for name in list(cls._processes):
            cls.close(name)

    # ------------------------------------------------------------------ extension helpers
    @classmethod
    def _cleanup_proxy_extensions(cls) -> None:
        if not cls.EXTENSIONS_ROOT.exists():
            return
        try:
            for item in cls.EXTENSIONS_ROOT.glob("cli_*"):
                import shutil

                shutil.rmtree(item, ignore_errors=True)
        except Exception:  # pragma: no cover
            LOGGER.debug("Proxy extension cleanup failed", exc_info=True)

    @classmethod
    def _create_proxy_extension(cls, username: str, password: str) -> Path:
        cls.EXTENSIONS_ROOT.mkdir(parents=True, exist_ok=True)
        ext_dir = cls.EXTENSIONS_ROOT / f"cli_{int(time.time()*1000)}"
        ext_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "manifest_version": 2,
            "name": "ProxyAuth (DirectParser)",
            "version": "1.0",
            "permissions": [
                "webRequest",
                "webRequestAuthProvider",
                "webRequestBlocking",
                "<all_urls>",
            ],
            "background": {"scripts": ["background.js"], "persistent": True},
        }
        (ext_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        background = f"""
chrome.webRequest.onAuthRequired.addListener(
  function(details) {{
    return {{ authCredentials: {{ username: '{username}', password: '{password}' }} }};
  }},
  {{ urls: ['<all_urls>'] }},
  ['blocking']
);
"""
        (ext_dir / "background.js").write_text(background, encoding="utf-8")
        return ext_dir


__all__ = ["ChromeLauncherDirectParser"]
