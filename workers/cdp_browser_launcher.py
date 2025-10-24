"""
CDP Browser Launcher — запускает браузеры через Chrome DevTools Protocol.
Использует BrowserFactory, чтобы применять нужные профили и прокси.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from ..services import accounts as account_service
from ..services.browser_factory import BrowserContextHandle, for_account, start_for_account
from ..services.proxy_manager import ProxyManager


class CDPBrowserLauncher:
    """Утилита для массового запуска браузеров в CDP-режиме."""

    WORKING_ACCOUNTS = [
        {"name": "dsmismirnov", "profile": ".profiles/wordstat_main", "port": 9222},
        {"name": "kuznepetya", "profile": ".profiles/kuznepetya", "port": 9223},
        {"name": "semenovmsemionov", "profile": ".profiles/semenovmsemionov", "port": 9224},
        {"name": "vfefyodorov", "profile": ".profiles/vfefyodorov", "port": 9225},
        {"name": "volkovsvolkow", "profile": ".profiles/volkovsvolkow", "port": 9226},
    ]

    def __init__(self) -> None:
        self.handles: List[BrowserContextHandle] = []

    # ------------------------------------------------------------------ #
    # Launch helpers
    # ------------------------------------------------------------------ #
    def _find_account(self, name: str):
        for account in account_service.list_accounts():
            if account.name == name:
                return account
        return None

    def launch_browser(self, descriptor: Dict) -> Optional[BrowserContextHandle]:
        account = self._find_account(descriptor["name"])
        if not account:
            print(f"[{descriptor['name']}] ERROR: аккаунт не найден.")
            return None

        try:
            handle = for_account(
                account_id=account.id,
                use_cdp=True,
                cdp_port=int(descriptor.get("port", 0)),
                profile_override=descriptor.get("profile"),
            )
        except Exception as exc:
            print(f"[{descriptor['name']}] ERROR: {exc}")
            return None

        profile_path = handle.metadata.get("profile_dir")
        if profile_path:
            print(f"[{descriptor['name']}] профиль: {profile_path}")
        self.handles.append(handle)
        return handle

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def launch_all_browsers(self, accounts: Optional[List[Dict]] = None) -> bool:
        accounts = accounts or self.WORKING_ACCOUNTS

        print("\n" + "=" * 70)
        print("   ЗАПУСК БРАУЗЕРОВ ДЛЯ ПАРСИНГА (CDP)")
        print("=" * 70)

        successful: List[Dict] = []
        self.handles = []

        for index, descriptor in enumerate(accounts):
            print(f"\n[{index + 1}/{len(accounts)}] {descriptor['name']}")
            handle = self.launch_browser(descriptor)
            if handle:
                successful.append(descriptor)
                print(f"  ✓ Запущен на порту {descriptor['port']}")
                if index < len(accounts) - 1:
                    time.sleep(2)
            else:
                print("  ✗ Не удалось запустить")

        print("\n" + "=" * 70)
        print(f"   РЕЗУЛЬТАТ: {len(successful)}/{len(accounts)} браузеров запущено")
        print("=" * 70)

        if not successful:
            print("\n✗ Не удалось запустить ни один браузер.")
            return False

        print("\nCDP адреса для подключения:")
        for descriptor in successful:
            print(f"  {descriptor['name']} -> http://127.0.0.1:{descriptor['port']}")
        print("\n✓ Браузеры готовы к парсингу.")
        return True

    def close_all_browsers(self) -> None:
        for handle in self.handles:
            try:
                handle.release_cb()
            except Exception:
                pass
        self.handles = []
        print("Все браузеры закрыты.")


def launch_browsers_for_parsing() -> bool:
    launcher = CDPBrowserLauncher()
    return launcher.launch_all_browsers()


def open_for_login(account_id: int, *, headless: bool = False, cdp_port: int = 9222) -> BrowserContextHandle:
    """Запуск браузера для логина с учётом привязанного прокси."""
    account = account_service.get_account(account_id)
    if account is None:
        raise ValueError(f"Account {account_id} not found")

    manager = ProxyManager.instance()
    proxy = manager.get(account.proxy_id) if getattr(account, "proxy_id", None) else None
    prefer_cdp = not (proxy and proxy.has_auth)

    return start_for_account(
        account_id=account.id,
        headless=headless,
        use_cdp=prefer_cdp,
        cdp_port=cdp_port,
        profile_override=account.profile_path,
    )
