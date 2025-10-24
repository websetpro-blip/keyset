#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автоматически добавляет логины и пароли к прокси в browser_settings.json.

Сценарий:
1. Берём текущий список аккаунтов из config/browser_settings.json.
2. Для каждого аккаунта проверяем поле "proxy".
   - Если прокси уже содержит credentials (user:pass@host:port) — оставляем как есть.
   - Если прокси указан без авторизации, ищем соответствующий сервер в config/proxies.json.
3. Если найден объект прокси с логином/паролем, обновляем строку до формата:
       scheme://user:pass@host:port
4. Перед сохранением создаём резервную копию browser_settings.json (с суффиксом .bak_<timestamp>).

Запуск:
    cd C:/AI/yandex/keyset
    python -m scripts.fix_proxy_credentials
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT_DIR / "config"
BROWSER_SETTINGS_PATH = CONFIG_DIR / "browser_settings.json"
PROXIES_PATH = CONFIG_DIR / "proxies.json"


def _load_json(path: Path) -> Dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"[ERROR] Файл {path} не найден.", file=sys.stderr)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Ошибка чтения {path}: {exc}", file=sys.stderr)
    return {}


def _normalize_host_port(server: str) -> Optional[Tuple[str, str]]:
    """Возвращает (scheme, host:port) или None."""
    if not server:
        return None
    scheme, sep, rest = server.partition("://")
    if sep:
        return scheme.lower(), rest
    # Без схемы — считаем http
    return "http", server


def _build_proxy_url(scheme: str, host_port: str, username: str, password: str) -> str:
    return f"{scheme}://{username}:{password}@{host_port}"


def _has_credentials(proxy_value: str | None) -> bool:
    if not proxy_value:
        return False
    return "@" in proxy_value and ":" in proxy_value.split("@")[-1]


def _collect_proxy_lookup() -> Dict[str, Dict[str, str]]:
    """
    Возвращает словарь {host_port: {"scheme": scheme, "username": ..., "password": ...}}
    на основе config/proxies.json.
    """
    payload = _load_json(PROXIES_PATH)
    entries = {}

    for proxy in payload.get("proxies", []):
        server = proxy.get("server") or ""
        norm = _normalize_host_port(server)
        if not norm:
            continue
        scheme, host_port = norm
        username = proxy.get("username") or ""
        password = proxy.get("password") or ""
        entries[host_port] = {
            "scheme": scheme,
            "username": username,
            "password": password,
        }
    return entries


def _backup_browser_settings() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = CONFIG_DIR / f"browser_settings.json.bak_{timestamp}"
    shutil.copy2(BROWSER_SETTINGS_PATH, backup_path)
    return backup_path


def fix_credentials() -> int:
    if not BROWSER_SETTINGS_PATH.exists():
        print(f"[ERROR] {BROWSER_SETTINGS_PATH} не найден.", file=sys.stderr)
        return 1

    data = _load_json(BROWSER_SETTINGS_PATH)
    accounts = data.get("accounts", [])
    if not isinstance(accounts, list):
        print("[ERROR] Некорректный формат browser_settings.json", file=sys.stderr)
        return 1

    proxy_lookup = _collect_proxy_lookup()
    if not proxy_lookup:
        print("[WARN] В proxies.json нет прокси с авторизацией. Изменений не будет.")

    updated = False

    for account in accounts:
        proxy_value = account.get("proxy") or ""
        if not proxy_value:
            continue

        if _has_credentials(proxy_value):
            continue  # уже содержит user:pass

        norm = _normalize_host_port(proxy_value)
        if not norm:
            continue

        scheme, host_port = norm
        credentials = proxy_lookup.get(host_port)
        if not credentials:
            print(f"[WARN] Не найден логин/пароль для {host_port} — пропускаю.")
            continue

        username = credentials.get("username", "")
        password = credentials.get("password", "")
        if not username:
            print(f"[WARN] У прокси {host_port} нет username — пропускаю.")
            continue

        new_value = _build_proxy_url(credentials.get("scheme", scheme), host_port, username, password)
        if new_value != proxy_value:
            print(f"[INFO] Обновляю прокси для аккаунта {account.get('name')}: {new_value}")
            account["proxy"] = new_value
            updated = True

    if not updated:
        print("[OK] Обновления не требуются. Все прокси уже содержат авторизацию.")
        return 0

    backup_path = _backup_browser_settings()
    BROWSER_SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    print(f"[OK] Прокси обновлены. Резервная копия: {backup_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(fix_credentials())
