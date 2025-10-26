# -*- coding: utf-8 -*-
"""Dry-run for login_selected proxy pipeline with UTF-8 logging."""
from __future__ import annotations

import argparse
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
for candidate in (str(PROJECT_ROOT), str(ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from yandex.keyset.services import accounts as accounts_service
from yandex.keyset.services.proxy_manager import ProxyManager
from yandex.keyset.services.chrome_launcher_directparser import ChromeLauncherDirectParser
from yandex.keyset.utils.proxy import proxy_to_playwright


LOG_FILE = ROOT / "logs" / "login_proxy_smoke.log"


def _log(message: str) -> None:
    """Append message both to stdout and the UTF-8 log file."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] [SMOKE] {message}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _extract_host_port(entry: str) -> Optional[str]:
    if not entry:
        return None
    candidate = entry.strip()
    if not candidate:
        return None
    if "://" in candidate:
        parsed = urlparse(candidate)
        host = parsed.hostname
        port = parsed.port
        if host and port:
            return f"{host}:{port}"
        return None
    if ":" in candidate:
        return candidate
    return None


def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _allocate_port(seed: int, used: set[int]) -> int:
    port = seed
    while port in used or _is_port_in_use(port):
        port += 1
    used.add(port)
    return port


def _resolve_accounts(requested: Sequence[str]):
    accounts = accounts_service.list_accounts()
    if not requested:
        return accounts
    wanted = {name.lower() for name in requested}
    return [acc for acc in accounts if getattr(acc, "name", "").lower() in wanted]


def _resolve_proxy(account) -> dict:
    manager = ProxyManager.instance()
    server_value: Optional[str] = None
    host_port: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    source = "none"

    proxy_id = getattr(account, "proxy_id", None)
    if proxy_id:
        proxy_obj = manager.get(proxy_id)
        if proxy_obj and proxy_obj.enabled:
            cfg = proxy_obj.playwright_config()
            server_value = cfg.get("server")
            host_port = _extract_host_port(cfg.get("server", ""))
            username = cfg.get("username")
            password = cfg.get("password")
            source = f"ProxyManager:{proxy_obj.id}"
        else:
            source = f"ProxyManager:{proxy_id}:disabled"

    if not host_port:
        raw_proxy = (getattr(account, "proxy", None) or "").strip()
        if raw_proxy:
            parsed = proxy_to_playwright(raw_proxy)
            if parsed and parsed.get("server"):
                server_value = parsed["server"]
                host_port = _extract_host_port(parsed["server"])
                username = parsed.get("username")
                password = parsed.get("password")
                source = "account_field"
            else:
                source = "account_field:invalid"

    return {
        "server": server_value,
        "host_port": host_port,
        "username": username,
        "password": password,
        "source": source,
    }


def _account_profile(account) -> str:
    profile = getattr(account, "profile_path", "") or ""
    if profile:
        return profile.replace("\\", "/")
    return f"C:/AI/yandex/.profiles/{account.name}"


def main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run proxy configuration for the KeySet login workflow (UTF-8)."
    )
    parser.add_argument(
        "-a",
        "--account",
        action="append",
        dest="accounts",
        help="Account name to check (repeatable). Without arguments checks all accounts.",
    )
    args = parser.parse_args(list(argv))

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _log(f"Log file: {LOG_FILE}")

    accounts = _resolve_accounts(args.accounts or [])
    if not accounts:
        _log("Нет аккаунтов для проверки. Добавьте их в БД или укажите корректное имя.")
        return 2

    used_ports: set[int] = set()
    for account in accounts:
        name = getattr(account, "name", getattr(account, "login", "unknown"))
        proxy_info = _resolve_proxy(account)
        port_seed = 9222 + (hash(name) % 100)
        port = _allocate_port(port_seed, used_ports)
        profile_path = _account_profile(account)

        if proxy_info["host_port"]:
            try:
                parsed = ChromeLauncherDirectParser._parse_proxy(  # type: ignore[attr-defined]
                    proxy_info["host_port"],
                    proxy_info["username"],
                    proxy_info["password"],
                )
            except Exception as exc:
                _log(f"{name}: ошибка разбора прокси ({proxy_info['host_port']}): {exc}")
                continue

            scheme = parsed["scheme"]
            host_port = f"{parsed['host']}:{parsed['port']}"
            auth_flag = "auth=yes" if proxy_info["username"] else "auth=no"
            masked_env = (
                f"{scheme}://{proxy_info['username']}:***@{host_port}"
                if proxy_info["username"]
                else f"{scheme}://{host_port}"
            )
            _log(
                f"{name}: DirectParser -> proxy={scheme}://{host_port}, "
                f"{auth_flag}, source={proxy_info['source']}, profile={profile_path}"
            )
            _log(f"{name}: HTTP_PROXY будет {masked_env}")
        else:
            _log(
                f"{name}: стандартный запуск без прокси -> port={port}, profile={profile_path}, "
                f"source={proxy_info['source']}"
            )

    _log("Готово. Проверьте логи и при необходимости скорректируйте настройки прокси.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
