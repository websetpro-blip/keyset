# -*- coding: utf-8 -*-
"""Smoke-тест запуска браузера с прокси (UTF-8)."""

from __future__ import annotations

import csv
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
REPO_ROOT = PROJECT_ROOT.parent
for candidate in (str(REPO_ROOT), str(PROJECT_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from yandex.keyset.services import accounts as accounts_service
from yandex.keyset.services.proxy_manager import ProxyManager, proxy_preflight, Proxy
from yandex.keyset.services.browser_factory import start_for_account, BrowserContextHandle


LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

CSV_HEADERS = [
    "time",
    "account",
    "profile_dir",
    "proxy_id",
    "mode",
    "preflight_ip",
    "page_ip",
    "wordstat_ok",
    "error",
]

CHECK_URL = "https://api.ipify.org?format=json"
WORDSTAT_URL = "https://wordstat.yandex.ru/#!/?region=225&view=table&words=ремонт"
PAGE_TIMEOUT_SEC = 12


def _safe_text(value: object) -> str:
    return str(value).replace("\n", " ").replace("\r", " ").strip()


def _iter_accounts(selected: Iterable[str]) -> List:
    all_accounts = accounts_service.list_accounts()
    if not selected:
        return all_accounts
    normalized = {name.lower() for name in selected}
    return [acc for acc in all_accounts if getattr(acc, "name", "").lower() in normalized]


def _release_handle(handle: BrowserContextHandle) -> None:
    try:
        handle.release_cb()
    except Exception:
        pass


def run_account(account, writer: csv.DictWriter) -> None:
    account_name = getattr(account, "name", getattr(account, "login", "unknown"))
    proxy_id = getattr(account, "proxy_id", None)
    proxy_obj: Optional[Proxy] = None
    proxy_manager = ProxyManager.instance()
    if proxy_id:
        proxy_obj = proxy_manager.acquire(proxy_id)
    else:
        proxy_obj = None

    row = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "account": account_name,
        "profile_dir": getattr(account, "profile_path", ""),
        "proxy_id": proxy_id or "",
        "mode": "",
        "preflight_ip": "",
        "page_ip": "",
        "wordstat_ok": "",
        "error": "",
    }

    def fail(message: str) -> None:
        row["error"] = message
        writer.writerow(row)
        print(row)

    try:
        if proxy_obj:
            preflight = proxy_preflight(proxy_obj)
            if preflight.get("ok"):
                row["preflight_ip"] = preflight.get("ip") or ""
            else:
                fail(f"preflight_fail: {preflight.get('error')}")
                return

        handle = start_for_account(account.id, headless=False, use_cdp=False)
        row["mode"] = handle.kind

        metadata = handle.metadata or {}
        if isinstance(metadata, dict):
            preflight_meta = metadata.get("preflight")
            if isinstance(preflight_meta, dict) and preflight_meta.get("ip"):
                row["preflight_ip"] = preflight_meta.get("ip")

        page = handle.page
        page.set_default_timeout(PAGE_TIMEOUT_SEC * 1000)

        ip_info = page.evaluate(
            "() => fetch('https://api.ipify.org?format=json').then(r => r.json())"
        )
        if isinstance(ip_info, dict):
            row["page_ip"] = ip_info.get("ip", "") or ""

        page.goto(WORDSTAT_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_SEC * 1000)
        locator = page.locator("input.textinput__control, input[type='text']").first
        locator.wait_for(timeout=PAGE_TIMEOUT_SEC * 1000)
        row["wordstat_ok"] = "YES"

    except Exception as exc:
        fail(f"{type(exc).__name__}: {_safe_text(exc)}")
        print(traceback.format_exc())
        return
    finally:
        try:
            if "handle" in locals():
                _release_handle(handle)
        except Exception:
            pass
        finally:
            if proxy_obj:
                try:
                    proxy_manager.release(proxy_obj)
                except Exception:
                    pass

    writer.writerow(row)
    print(row)


def main(argv: List[str]) -> int:
    requested = [arg for arg in argv if not arg.startswith("-")]
    accounts = _iter_accounts(requested)
    if not accounts:
        print("Нет аккаунтов для проверки.")
        return 2

    csv_path = LOG_DIR / f"proxy_smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for account in accounts:
            run_account(account, writer)

    print(f"\nSMOKE DONE -> {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
