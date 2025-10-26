# -*- coding: utf-8 -*-
'''Launch Google Chrome profiles with proxy support.

This module wraps subprocess.Popen to start a regular Chrome instance
(for manual browsing) with proper proxy and profile handling inside the
C:/AI/yandex workspace.
'''
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional, Sequence

LOGGER = logging.getLogger(__name__)


class ChromeLauncher:
    """Utility for launching system Chrome with a specific profile."""

    _CHROME_CANDIDATES: Sequence[Path] = (
        Path(r"C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path(r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
    )

    BASE_DIR = Path(r"C:/AI/yandex")
    DEFAULT_START_URL = "about:blank"
    EXTENSIONS_ROOT = BASE_DIR / "runtime" / "proxy_extensions"

    _processes: Dict[str, Dict[str, Optional[Path]]] = {}

    @classmethod
    def _resolve_chrome_executable(cls) -> str:
        for candidate in cls._CHROME_CANDIDATES:
            if candidate.exists():
                return str(candidate)
        raise FileNotFoundError(
            "Chrome executable not found. Adjust ChromeLauncher._CHROME_CANDIDATES."
        )

    @classmethod
    def _cleanup_proxy_extensions(cls) -> None:
        if not cls.EXTENSIONS_ROOT.exists():
            return
        active = {data.get('extension') for data in cls._processes.values() if data.get('extension')}
        for item in cls.EXTENSIONS_ROOT.glob('cli_*'):
            if item in active:
                continue
            shutil.rmtree(item, ignore_errors=True)

    @classmethod
    def _create_proxy_extension(cls, username: str, password: str) -> Path:
        cls.EXTENSIONS_ROOT.mkdir(parents=True, exist_ok=True)
        ext_dir = cls.EXTENSIONS_ROOT / f'cli_{int(time.time() * 1000)}'
        ext_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            'manifest_version': 3,
            'name': 'ProxyAuth (KeySet)',
            'version': '1.0',
            'permissions': ['webRequest', 'webRequestAuthProvider', 'webRequestBlocking'],
            'host_permissions': ['<all_urls>'],
            'background': {'service_worker': 'background.js'},
            'minimum_chrome_version': '109',
        }
        (ext_dir / 'manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

        background = """chrome.webRequest.onAuthRequired.addListener(
  async () => ({ authCredentials: { username: '%s', password: '%s' } }),
  { urls: ['<all_urls>'] },
  ['blocking']
);

console.log('[ProxyAuth] service worker registered');
""" % (username, password)
        (ext_dir / 'background.js').write_text(background, encoding='utf-8')
        return ext_dir

    @classmethod
    def _normalise_profile_path(cls, profile_path: Optional[str], account: str) -> Path:
        """Вернуть фактический путь профиля Chrome.

        Исторически рабочие профили лежат в ``C:/AI/yandex/.profiles``.
        Текущая рабочая директория также располагается в ``C:/AI/yandex``.
        По-прежнему поддерживаем старые абсолютные пути и не создаём новую
        пустую папку, если уже существует профиль из «легаси»-сборок.
        """

        legacy_root = Path(r"C:/AI/yandex")
        base_root = cls.BASE_DIR
        candidates: list[Path] = []

        def add_candidate(path: Path) -> None:
            resolved = path if path.is_absolute() else path
            if resolved not in candidates:
                candidates.append(resolved)

        if profile_path:
            raw = Path(str(profile_path).strip())
            if raw.is_absolute():
                add_candidate(raw)
                try:
                    relative = raw.relative_to(legacy_root)
                except ValueError:
                    pass
                else:
                    add_candidate(base_root / relative)
            else:
                add_candidate(base_root / raw)
                add_candidate(legacy_root / raw)
        else:
            add_candidate(base_root / ".profiles" / account)
            add_candidate(legacy_root / ".profiles" / account)

        for candidate in candidates:
            if candidate and candidate.exists():
                return candidate.resolve()

        # If nothing exists yet, fallback to first candidate (creates under new workspace)
        return candidates[0].resolve()

    @classmethod
    def _terminate_existing(cls, account: str) -> None:
        data = cls._processes.get(account)
        proc = data.get('proc') if data else None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            except Exception as exc:  # pragma: no cover
                LOGGER.warning("Unable to terminate Chrome for %s: %s", account, exc)
        if data and data.get('extension'):
            shutil.rmtree(data['extension'], ignore_errors=True)
        cls._processes.pop(account, None)

    @classmethod
    def launch(
        cls,
        account: str,
        profile_path: Optional[str],
        cdp_port: int,
        proxy_server: Optional[str] = None,
        *,
        proxy_username: Optional[str] = None,
        proxy_password: Optional[str] = None,
        start_url: Optional[str] = None,
    ) -> subprocess.Popen:
        """Launch Chrome and return the running ``Popen`` object."""
        chrome_path = cls._resolve_chrome_executable()
        profile_dir = cls._normalise_profile_path(profile_path, account)
        profile_dir.mkdir(parents=True, exist_ok=True)

        cls._terminate_existing(account)

        args = [
            chrome_path,
            f"--user-data-dir={profile_dir.as_posix()}",
            f"--remote-debugging-port={cdp_port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-blink-features=AutomationControlled",
        ]

        env = os.environ.copy()

        extension_dir: Optional[Path] = None
        if proxy_server:
            scheme, sep, rest = proxy_server.partition('://')
            if sep:
                server_host = rest
                proxy_scheme = scheme or 'http'
            else:
                proxy_scheme = 'http'
                server_host = proxy_server

            args.append(f"--proxy-server={proxy_scheme}://{server_host}")

            if proxy_username and proxy_password:
                cls._cleanup_proxy_extensions()
                extension_dir = cls._create_proxy_extension(proxy_username, proxy_password)
                ext_path = extension_dir.as_posix()
                args.extend([
                    f"--load-extension={ext_path}",
                    f"--disable-extensions-except={ext_path}",
                ])
                env_proxy = f"{proxy_scheme}://{proxy_username}:{proxy_password}@{server_host}"
            else:
                env_proxy = f"{proxy_scheme}://{server_host}"

            env.update({
                'HTTP_PROXY': env_proxy,
                'http_proxy': env_proxy,
                'HTTPS_PROXY': env_proxy,
                'https_proxy': env_proxy,
            })

        args.append(start_url or cls.DEFAULT_START_URL)

        LOGGER.info("Launching Chrome for %s (profile=%s, port=%s)", account, profile_dir, cdp_port)
        proc = subprocess.Popen(args, env=env)
        cls._processes[account] = {'proc': proc, 'extension': extension_dir}
        return proc

    @classmethod
    def terminate(cls, account: str) -> None:
        cls._terminate_existing(account)

    @classmethod
    def terminate_all(cls) -> None:
        for name in list(cls._processes):
            cls._terminate_existing(name)
